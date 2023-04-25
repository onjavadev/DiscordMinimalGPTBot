# Discord chatGPT minimalistic bot written in Pyhton 3.
## Features
- To address the bot, just mention it in channel
- Context per channel, with customizable limit of tokens. You can discuss some topic with friends and chatbot not mixing context in different channels.
- Channel history is saved in SQLite database
- Secrets are taken from .env file 
- If assistant answer is more than limit in size, messages are sent in channel as batch
- Very small code footprint and easy to understand
