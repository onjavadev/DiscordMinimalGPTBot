import os
import discord
import openai
import json
import sqlite3
import tiktoken
from dotenv import load_dotenv
import log
import asyncio
from concurrent.futures import ThreadPoolExecutor
import functools

# setup logger
logger = log.setup_logger(__name__)

# load secrets from .env file
load_dotenv()

#assign secrets to variables
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
openai.api_key = OPENAI_API_KEY

#setup intents and assign client
intents = discord.Intents.default()
intents.messages = True
intents.members = True
client = discord.Client(intents=intents)

TOKEN_LIMIT = 4096 - 1024
MODEL_ENGINE = "gpt-3.5-turbo-0301"
MAX_MESSAGE_LENGTH = 2000

def count_tokens(text, model_engine):
   tokenizer = tiktoken.encoding_for_model(model_engine)
   tokens = tokenizer.encode(text)
   return len(tokens)

def truncate_conversation_history(conversation_history, token_limit, model_engine):
   total_tokens = 0
   total_tokens_before = 0

   # Count total tokens
   for msg in conversation_history:
      total_tokens += 4
      total_tokens += count_tokens(msg["content"], model_engine)

   # Total tokens before truncate
   total_tokens_before = total_tokens

   while total_tokens > token_limit:
      removed_message = conversation_history.pop(0)
      total_tokens -= count_tokens(removed_message["content"], model_engine)

   logger.info(f'Tokens before truncate: {total_tokens_before}; Tokens after truncate {total_tokens}')
   return conversation_history

# Set up the SQLite database and create a table for storing conversation history
db = sqlite3.connect("chat_history.sqlite")
cursor = db.cursor()
cursor.execute(
   """CREATE TABLE IF NOT EXISTS chat_history (
      id INTEGER PRIMARY KEY,
      channel_id INTEGER NOT NULL,
      user_id TEXT,
      user_name TEXT,
      message_role TEXT NOT NULL,
      message_content TEXT NOT NULL
   )"""
)
db.commit()

def load_conversation_history(channel_id):
   # fetch only 20 last messages from database
   cursor.execute("SELECT message_role, message_content FROM chat_history WHERE channel_id=? ORDER BY id DESC LIMIT 20", (channel_id,))
   rows = cursor.fetchall()
   history = [{"role": row[0], "content": row[1]} for row in rows]
   history.reverse()
   return history

def save_conversation_history(channel_id, user_id, user_name, message):
   cursor.execute(
      "INSERT INTO chat_history (channel_id, user_id, user_name, message_role, message_content) VALUES (?, ?, ?, ?, ?)",
      (channel_id, user_id, user_name, message["role"], message["content"])
   )
   db.commit()

# Wrap call to OpenAI server not to block Discord event handler
async def create_chat_completion_async(model_engine, conversation_history):
   loop = asyncio.get_event_loop()
   with ThreadPoolExecutor() as executor:
      partial_func = functools.partial(openai.ChatCompletion.create, model=model_engine, messages=conversation_history)
      response = await loop.run_in_executor(executor, partial_func)
   return response

# When bot is ready print log information like guilds and users information
@client.event
async def on_ready():
   print(f'{client.user} is connected to Discord!')
   for guild in client.guilds:
      logger.info(
         f'{client.user} is connected to guild:' f'{guild.name}(id: {guild.id})'
      )
      members = '\n - '.join([member.name for member in guild.members])
      logger.info(f'Guild Members:\n - {members}')

# When bot see a message
@client.event
async def on_message(message):
   # protect from recursion
   if message.author == client.user:
      return

   # Check if the bot is mentioned in the message
   if client.user in message.mentions:
      channel_id = message.channel.id
      input_text = message.content.strip()
      logger.info(f'Message on channel {channel_id} from {message.author}: {input_text}')

      # Load the channel's conversation history
      conversation_history = load_conversation_history(channel_id)
      logger.info(f'Loaded conversation history')

      # Add the user's message to the conversation history
      user_message = {"role": "user", "content": input_text}
      conversation_history.append(user_message)

      # Save the user's message
      save_conversation_history(channel_id, str(message.author.id), message.author.name, user_message)
      logger.info(f'Updated conversation history with user message')

      # Truncate conversation_history if it exceeds the token limit
      conversation_history = truncate_conversation_history(conversation_history, TOKEN_LIMIT, MODEL_ENGINE)

      # Send async request and await response
      logger.info(f'Sending request to OpenAI...')
      response = await create_chat_completion_async(MODEL_ENGINE, conversation_history)
      assistant_response = response['choices'][0]['message']['content']
      logger.info(f'Received response from OpenAI: {assistant_response}')

      # Add the AI's response to the conversation history
      assistant_message = {"role": "assistant", "content": assistant_response}
      # conversation_history.append(assistant_message)

      # Save the AI's response
      save_conversation_history(channel_id, str(message.author.id), message.author.name, assistant_message)
      logger.info(f'Updated conversation history with assistant response')

      # Split the assistant_response into smaller chunks if it's too long
      if len(assistant_response) > MAX_MESSAGE_LENGTH:
         response_chunks = [assistant_response[i:i + MAX_MESSAGE_LENGTH] for i in range(0, len(assistant_response), MAX_MESSAGE_LENGTH)]
      else:
         response_chunks = [assistant_response]
      # Send the response chunks as separate messages
      for chunk in response_chunks:
         await message.channel.send(chunk)
      logger.info(f'Sent response to Discord server')

client.run(DISCORD_TOKEN)
