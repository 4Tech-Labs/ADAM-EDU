# Optional local development shortcuts. In Windows, prefer the documented direct commands.
.PHONY: help dev-frontend dev-backend dev-langgraph dev

help:
	@echo "Available commands:"
	@echo "  make dev-frontend    - Starts the frontend development server (Vite)"
	@echo "  make dev-backend     - Starts the backend API server (runtime profile launcher)"
	@echo "  make dev-langgraph   - Starts the LangGraph development server"
	@echo "  make dev             - Starts both frontend and backend API development servers"

dev-frontend:
	@echo "Starting frontend development server..."
	@cd frontend && npm run dev

dev-backend:
	@echo "Starting backend API development server..."
	@cd backend && uv run python -m shared.app

dev-langgraph:
	@echo "Starting LangGraph development server..."
	@cd backend && uv run langgraph dev

# Run frontend and backend concurrently
dev:
	@echo "Starting frontend and backend API development servers..."
	@make dev-frontend & make dev-backend 
