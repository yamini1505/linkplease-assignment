from fastapi import FastAPI, Depends, BackgroundTasks, Request, HTTPException
from sqlalchemy.orm import Session
from dotenv import load_dotenv
import os
import uuid
import asyncio
import httpx
import hmac
import hashlib

from .database import engine, Base, SessionLocal
from .models import Rule, Delivery, Stats
from .schemas import RuleCreate


# --------------------------------------------------
# LOAD ENVIRONMENT VARIABLES
# --------------------------------------------------

load_dotenv()

PSEUDOGRAM_API_KEY = os.getenv("PSEUDOGRAM_API_KEY")

PSEUDOGRAM_BASE_URL = "https://pseudogram-api.onrender.com"


# --------------------------------------------------
# DATABASE
# --------------------------------------------------

Base.metadata.create_all(bind=engine)


# --------------------------------------------------
# FASTAPI APP
# --------------------------------------------------

app = FastAPI()


# --------------------------------------------------
# DATABASE DEPENDENCY
# --------------------------------------------------

def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


# --------------------------------------------------
# HOME
# --------------------------------------------------

@app.get("/")
def home():
    return {
        "message": "LinkPlease backend is running!"
    }


# --------------------------------------------------
# CREATE RULE
# --------------------------------------------------

@app.post("/rules", status_code=201)
def create_rule(
    rule: RuleCreate,
    db: Session = Depends(get_db)
):
    new_rule = Rule(
        rule_id=str(uuid.uuid4()),
        keyword=rule.keyword,
        dm_message=rule.dm_message
    )

    db.add(new_rule)
    db.commit()
    db.refresh(new_rule)

    return {
        "rule_id": new_rule.rule_id,
        "keyword": new_rule.keyword,
        "dm_message": new_rule.dm_message
    }


# --------------------------------------------------
# WEBHOOK
# --------------------------------------------------

@app.post("/webhook")
async def webhook(
    request: Request,
    background_tasks: BackgroundTasks
):
    # Read the ORIGINAL request body.
    # We need the raw body for signature verification.
    body = await request.body()

    # Get the signature sent by PseudoGram.
    received_signature = request.headers.get(
        "X-PseudoGram-Signature"
    )

    # If there is no signature, reject the request.
    if not received_signature:
        raise HTTPException(
            status_code=401,
            detail="Missing webhook signature"
        )

    # Create the signature ourselves using our API key.
    expected_signature = (
        "sha256="
        + hmac.new(
            PSEUDOGRAM_API_KEY.encode(),
            body,
            hashlib.sha256
        ).hexdigest()
    )

    # Compare the received signature with our signature.
    if not hmac.compare_digest(
        received_signature,
        expected_signature
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid webhook signature"
        )

    # The signature is correct.
    # Now convert the JSON body into a Python dictionary.
    data = await request.json()

    # Return quickly.
    # The real processing happens in the background.
    background_tasks.add_task(
        process_webhook,
        data
    )

    return {
        "status": "accepted"
    }


# --------------------------------------------------
# PROCESS WEBHOOK
# --------------------------------------------------

async def process_webhook(data):
    print("PROCESS_WEBHOOK STARTED")

    db = SessionLocal()

    try:
        # Only process comment.created events.
        event_type = data.get("event_type")

        if event_type and event_type != "comment.created":
            print("Ignoring event:", event_type)
            return

        text = data["data"]["text"]
        user_id = data["data"]["from"]["user_id"]
        comment_id = data["data"]["comment_id"]

        # Find all rules.
        rules = db.query(Rule).all()

        for rule in rules:

            # Case-insensitive keyword matching.
            if rule.keyword.lower() in text.lower():

                # Check whether this user already received
                # this rule.
                existing = db.query(Delivery).filter(
                    Delivery.rule_id == rule.rule_id,
                    Delivery.user_id == user_id
                ).first()

                if existing:
                    print("Duplicate blocked")

                    # Increase duplicate counter.
                    stats = db.query(Stats).first()

                    if stats is None:
                        stats = Stats(
                            duplicates_blocked=1
                        )
                        db.add(stats)
                    else:
                        stats.duplicates_blocked += 1

                    db.commit()

                    continue

                print("Rule matched:", rule.keyword)

                # Send the DM.
                response = await send_dm(
                    user_id,
                    rule.dm_message,
                    comment_id
                )

                # PseudoGram accepted the request.
                # 200/202 means queued, not necessarily delivered.
                if response.status_code in (200, 202):

                    response_data = response.json()

                    dm_id = response_data.get("dm_id")

                    delivery = Delivery(
                        rule_id=rule.rule_id,
                        user_id=user_id,
                        comment_id=comment_id,
                        status="queued",
                        dm_id=dm_id
                    )

                    db.add(delivery)
                    db.commit()

                    print("DM successfully queued")
                    print("DM ID:", dm_id)

                else:
                    print(
                        "DM failed:",
                        response.status_code
                    )

                    # Store failed attempts instead of
                    # silently losing them.
                    delivery = Delivery(
                        rule_id=rule.rule_id,
                        user_id=user_id,
                        comment_id=comment_id,
                        status="failed",
                        dm_id=None
                    )

                    db.add(delivery)
                    db.commit()

    except Exception as e:
        print("Webhook processing error:", e)

    finally:
        db.close()


# --------------------------------------------------
# SEND DM
# --------------------------------------------------

async def send_dm(
    user_id,
    message,
    comment_id
):
    url = (
        f"{PSEUDOGRAM_BASE_URL}"
        "/v1/dm/send"
    )

    headers = {
        "X-API-Key": PSEUDOGRAM_API_KEY,
        "Content-Type": "application/json",

        # Same user + comment should not create
        # another DM at the API level.
        "Idempotency-Key": f"{user_id}-{comment_id}"
    }

    payload = {
        "recipient_user_id": user_id,
        "message": message,
        "comment_id": comment_id
    }

    async with httpx.AsyncClient() as client:

        response = await client.post(
            url,
            headers=headers,
            json=payload,
            timeout=20.0
        )

    print(
        "DM API response:",
        response.status_code
    )

    print(response.text)

    return response


# --------------------------------------------------
# RECONCILE ONE DELIVERY
# --------------------------------------------------

async def check_dm_status(
    delivery_id,
    dm_id
):
    """
    Ask PseudoGram for the current status of one DM.
    """

    url = (
        f"{PSEUDOGRAM_BASE_URL}"
        f"/v1/dm/{dm_id}"
    )

    headers = {
        "X-API-Key": PSEUDOGRAM_API_KEY
    }

    try:

        async with httpx.AsyncClient() as client:

            response = await client.get(
                url,
                headers=headers,
                timeout=20.0
            )

        print(
            "Checking DM:",
            dm_id,
            "HTTP:",
            response.status_code
        )

        if response.status_code != 200:
            print(
                "Could not check DM:",
                response.text
            )
            return

        data = response.json()

        new_status = data.get("status")

        print(
            "PseudoGram status:",
            dm_id,
            new_status
        )

        # Update our database.
        db = SessionLocal()

        try:

            delivery = db.query(Delivery).filter(
                Delivery.id == delivery_id
            ).first()

            if delivery is None:
                return

            if new_status in (
                "queued",
                "delivered",
                "failed"
            ):

                delivery.status = new_status

                db.commit()

                print(
                    "Database delivery status updated:",
                    new_status
                )

        finally:
            db.close()

    except Exception as e:

        print(
            "Status check error:",
            dm_id,
            e
        )


# --------------------------------------------------
# RECONCILE ALL QUEUED DELIVERIES
# --------------------------------------------------

async def reconcile_deliveries():
    """
    Find queued deliveries and ask PseudoGram
    for their latest status.
    """

    db = SessionLocal()

    try:

        deliveries = db.query(Delivery).filter(
            Delivery.status == "queued",
            Delivery.dm_id.isnot(None)
        ).limit(10).all()

        # Make a simple list so we can close
        # the database session before making HTTP calls.
        delivery_list = [
            (
                delivery.id,
                delivery.dm_id
            )
            for delivery in deliveries
        ]

    finally:
        db.close()

    if not delivery_list:
        return

    print(
        "Reconciling",
        len(delivery_list),
        "queued DM(s)"
    )

    for delivery_id, dm_id in delivery_list:

        await check_dm_status(
            delivery_id,
            dm_id
        )


# --------------------------------------------------
# BACKGROUND RECONCILIATION LOOP
# --------------------------------------------------

async def reconciliation_loop():
    """
    Run reconciliation repeatedly.

    Every 10 seconds we check up to 10 queued
    deliveries.
    """

    print("Reconciliation worker started")

    while True:

        try:

            await reconcile_deliveries()

        except Exception as e:

            print(
                "Reconciliation error:",
                e
            )

        # Wait 10 seconds before checking again.
        await asyncio.sleep(10)


# --------------------------------------------------
# START RECONCILIATION WORKER
# --------------------------------------------------

@app.on_event("startup")
async def startup_event():

    app.state.reconciliation_task = (
        asyncio.create_task(
            reconciliation_loop()
        )
    )


# --------------------------------------------------
# STOP RECONCILIATION WORKER
# --------------------------------------------------

@app.on_event("shutdown")
async def shutdown_event():

    task = getattr(
        app.state,
        "reconciliation_task",
        None
    )

    if task:

        task.cancel()

        try:
            await task

        except asyncio.CancelledError:
            pass

    print("Reconciliation worker stopped")


# --------------------------------------------------
# STATS
# --------------------------------------------------

@app.get("/stats")
def get_stats(
    db: Session = Depends(get_db)
):

    sent = db.query(Delivery).filter(
        Delivery.status == "delivered"
    ).count()

    failed = db.query(Delivery).filter(
        Delivery.status == "failed"
    ).count()

    queued = db.query(Delivery).filter(
        Delivery.status == "queued"
    ).count()

    stats = db.query(Stats).first()

    if stats is None:

        stats = Stats(
            duplicates_blocked=0
        )

        db.add(stats)
        db.commit()
        db.refresh(stats)

    return {
        "sent": sent,
        "failed": failed,
        "queued": queued,
        "duplicates_blocked":
            stats.duplicates_blocked
    }