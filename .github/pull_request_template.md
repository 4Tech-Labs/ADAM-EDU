## Summary

- What changed?
- Why was it necessary?

## Validation

- [ ] `uv run --directory backend pytest -q`
- [ ] `uv run --directory backend mypy src`
- [ ] `npm --prefix frontend run lint`
- [ ] `npm --prefix frontend run build`
- [ ] `npm --prefix frontend run test`

## Checklist

- [ ] Single-purpose PR
- [ ] No secrets added
- [ ] Docs updated if behavior or setup changed
- [ ] Production `DATABASE_URL` validated to Supavisor transaction mode (`:6543`)
- [ ] Critical DB paths map saturation/timeouts to `503 + Retry-After + detail code`
- [ ] Tests cover backpressure contract on `/api/auth/me`, `/api/authoring/jobs`, and `/api/authoring/jobs/{job_id}/progress`
- [ ] Ready for squash merge
