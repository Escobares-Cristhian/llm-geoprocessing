- To run the main.py just run:  
`docker compose -f docker/compose.dev.yaml run --rm --build maie-dev python -m llm_geoprocessing.app.main`

- To run the chat_only_llm.py just run:  
`docker compose -f docker/compose.dev.yaml run --rm --build maie-dev python -m llm_geoprocessing.app.experiments.chat_only_llm`

- To run the chatbot.py just run:  
`docker compose -f docker/compose.dev.yaml run --rm --build maie-dev python -m llm_geoprocessing.app.chatbot.chatbot`