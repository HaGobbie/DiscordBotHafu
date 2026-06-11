# Use a lightweight, official Python image
FROM python:3.11-slim

# Set the active working directory inside the system
WORKDIR /app

# Copy dependency configuration and install packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the bot application code
COPY . .

# Wake Hafu up!
CMD ["python", "app.py"]