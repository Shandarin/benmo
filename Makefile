.PHONY: help config up down logs ps build infra-install infra-check infra-synth

help:
	@echo "Benmo development commands"
	@echo "  make config         Validate the Compose file"
	@echo "  make up             Build and start the local stack"
	@echo "  make down           Stop containers (keeps volumes)"
	@echo "  make logs           Follow service logs"
	@echo "  make ps             Show service health"
	@echo "  make build          Build API and worker images"
	@echo "  make infra-install  Install CDK dependencies"
	@echo "  make infra-check    Type-check CDK"
	@echo "  make infra-synth    Synthesize CloudFormation"

config:
	docker compose config --quiet

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

ps:
	docker compose ps

build:
	docker compose build backend research-worker

infra-install:
	npm --prefix infra install

infra-check:
	npm --prefix infra run check

infra-synth:
	npm --prefix infra run synth

