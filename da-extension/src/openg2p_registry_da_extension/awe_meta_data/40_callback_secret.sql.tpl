INSERT INTO "public"."callback_secret" (
    "id",
    "caller_service",
    "secret_hash",
    "status",
    "rotated_at",
    "created_at",
    "updated_at"
) VALUES (
    '${AWE_CALLBACK_SECRET_ID}',
    '${AWE_CALLBACK_CALLER_SERVICE}',
    '${AWE_CALLBACK_HMAC_SECRET}',
    'active',
    NOW(),
    NOW(),
    NOW()
)
ON CONFLICT ("id") DO UPDATE SET
    "caller_service" = EXCLUDED."caller_service",
    "updated_at" = NOW();

-- Bring this registry's in-flight requests in line with the caller_service
-- registered above. AWE copies callback_url onto the request at creation and
-- onto each webhook_delivery at event time, so a URL change alone only
-- affects requests created afterwards; anything already open keeps posting
-- to the old address. Requests are matched on callback_secret_id (the AWE DB
-- is shared, other registries' rows are untouched), and only deliveries that
-- never landed are requeued: delivered rows stay as they are, exhausted ones
-- get a fresh attempt budget. next_attempt_at is set to the event's own
-- timestamp so the dispatcher, which orders by it, replays in the original
-- order. Idempotent: a no-op once every row carries the current URL.
UPDATE "public"."approval_request"
SET "callback_url" = '${AWE_CALLBACK_CALLER_SERVICE}'
WHERE "callback_secret_id" = '${AWE_CALLBACK_SECRET_ID}'
  AND "callback_url" IS DISTINCT FROM '${AWE_CALLBACK_CALLER_SERVICE}';

UPDATE "public"."webhook_delivery" AS d
SET "url" = '${AWE_CALLBACK_CALLER_SERVICE}',
    "status" = 'pending',
    "attempt" = 0,
    "next_attempt_at" = e."created_at"
FROM "public"."approval_event" AS e
JOIN "public"."approval_request" AS r ON r."id" = e."request_id"
WHERE d."event_id" = e."id"
  AND r."callback_secret_id" = '${AWE_CALLBACK_SECRET_ID}'
  AND d."status" <> 'delivered'
  AND d."url" IS DISTINCT FROM '${AWE_CALLBACK_CALLER_SERVICE}';
