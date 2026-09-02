-- website/migrations/014_newsletter_unsubscribe.sql
-- Add unsubscribe token and status to newsletter subscribers table.

ALTER TABLE newsletter_subscribers ADD COLUMN IF NOT EXISTS unsubscribe_token TEXT UNIQUE;
ALTER TABLE newsletter_subscribers ADD COLUMN IF NOT EXISTS unsubscribed_at TIMESTAMPTZ;
ALTER TABLE newsletter_subscribers ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'subscribed';
