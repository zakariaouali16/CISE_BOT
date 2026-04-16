# 1. Choose the base environment (a lightweight version of Python 3.10)
FROM python:3.10-slim

# 2. Set the working directory inside the container
WORKDIR /app

# 3. Copy your requirements file first (this helps with caching)
COPY requirements.txt .

# 4. Install the required Python packages
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy the rest of your bot's code into the container
COPY . .

# 6. Tell the container what command to run when it starts
CMD ["python", "app.py"]