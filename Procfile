api: cd backend && python -m app --reload
agent: cd backend && python -m agent.agent dev
calls: cd backend && celery -A worker.celery_app worker -Q calls -c 1 -n calls@%h --pool=solo
postcall: cd backend && celery -A worker.celery_app worker -Q postcall -c 1 -n postcall@%h --pool=solo
beat: cd backend && celery -A worker.celery_app beat
web: cd frontend && npm run dev
