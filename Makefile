X11 := xhost +local: # Only if using GUI with X11
COMPOSE := docker compose -f docker/compose.dev.yaml

LOG_ENV :=
ifneq ($(strip $(log_level)),)
LOG_ENV := --env GEOLLM_LOG_LEVEL=$(log_level)
endif

.PHONY: run
run:
	$(X11)
	$(COMPOSE) run --rm --build $(LOG_ENV) geollm python -m llm_geoprocessing.app.main
