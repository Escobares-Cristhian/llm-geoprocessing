- To run the main.py just run:  
`docker compose -f docker/compose.dev.yaml run --rm --build geollm python -m llm_geoprocessing.app.main`

- PD: To run with GUI, select use_gui=True in 'main.py' and also execute this in every new terminal:
`xhost +local:`
After execute the above command as normal

---

- To run the main.py with custom logger level (e.g., DEBUG) just run:
`docker compose -f docker/compose.dev.yaml run --rm --build --env GEOLLM_LOG_LEVEL=DEBUG geollm python -m llm_geoprocessing.app.main`

- To run the chat_only_llm.py just run:  
`docker compose -f docker/compose.dev.yaml run --rm --build geollm python -m llm_geoprocessing.app.experiments.chat_only_llm`

- To run the chatbot.py just run:  
`docker compose -f docker/compose.dev.yaml run --rm --build geollm python -m llm_geoprocessing.app.chatbot.chatbot`

- To get gee-sa.json file to authenticate with Google Earth Engine, execute this script in the terminal:
`bash secrets/create_gee-sa.sh`

- For executing a JSON instruction file, run:
`docker compose -f docker/compose.dev.yaml run --rm --build geollm python -m llm_geoprocessing.app.dev_tests.run_geoprocess_json --file tmp/json_instruction_example.json`

- TO get the logs:
`docker compose -f docker/compose.dev.yaml logs --no-log-prefix gee | tail -n 100`