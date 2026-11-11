ALTER TABLE public.media DROP COLUMN public_path;
ALTER TABLE public.job_media ADD COLUMN public_path text NOT NULL;

ALTER TABLE public.job_request ADD COLUMN created_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE public.job_request ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE public.job_events ADD COLUMN created_at timestamptz NOT NULL DEFAULT now();

CREATE TRIGGER job_request_set_updated_at
    BEFORE UPDATE ON public.job_request
    FOR EACH ROW
EXECUTE FUNCTION public.set_updated_at();
