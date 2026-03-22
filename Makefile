.PHONY: backend frontend dev install-backend install-frontend install clean-ports temporal worker

# Run backend (FastAPI with uvicorn)
backend:
	cd backend && uvicorn main:app --reload --port 8000

# Run frontend (Vite dev server)
frontend:
	cd frontend && npm run dev

# Run Temporal dev server (requires temporal CLI: https://docs.temporal.io/cli)
temporal:
	temporal server start-dev --db-filename temporal.db

# Run Temporal worker
worker:
	cd backend && python -m temporal.worker

# Run everything concurrently (Temporal + backend + worker + frontend)
dev:
	@echo "Starting Temporal, backend, worker, and frontend..."
	@trap 'kill 0' EXIT; \
		$(MAKE) temporal & \
		sleep 3 && $(MAKE) backend & \
		sleep 4 && $(MAKE) worker & \
		$(MAKE) frontend & \
		wait

# Port cleanup
clean-ports:
	@echo "Cleaning ports 8000 and 5173..."
	@lsof -ti:8000,5173 | xargs kill -9 2>/dev/null || true

# Install dependencies
install-backend:
	cd backend && pip install -r requirements.txt

install-frontend:
	cd frontend && npm install

install: install-backend install-frontend
