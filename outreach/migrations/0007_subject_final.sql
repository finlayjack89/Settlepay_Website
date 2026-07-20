-- 0007_subject_final.sql — reviewable subject lines (playbook v2.0).
-- v1.x generated no subject at all: every drafts row stored subject = NULL and
-- send.py posts `subject or ""`, so a live send would have gone out with an empty
-- Subject header. v2.0 has the model return {subject, body}, which makes the subject
-- a reviewable artefact — and therefore one a human must be able to correct.
--
-- Mirrors the body_original/body_final split exactly: `subject` is what the model
-- wrote and stays immutable as the audit record; `subject_final` is what a reviewer
-- approved and is what actually sends.
alter table outreach.drafts add column if not exists subject_final text;
