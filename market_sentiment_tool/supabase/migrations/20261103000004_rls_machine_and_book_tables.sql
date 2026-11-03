-- Security fix (deep dive 2026-11-03): api_keys, api_key_events and book_activations shipped with RLS off and
-- full anon grants, and the publishable key is public, so anyone could mint a machine key, change Book 2's
-- activations or erase the audit trail. The API uses the service role, which bypasses RLS. Applied 2026-11-03.
ALTER TABLE public.api_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.api_key_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.book_activations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.api_keys, public.api_key_events, public.book_activations FROM anon, authenticated;
