
from flask import Flask,jsonify,render_template,request,flash,redirect,make_response,url_for,session
from pymongo import MongoClient
import os 
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash,check_password_hash
from werkzeug.debug import DebuggedApplication
import uuid
from datetime import datetime
import jwt
from functools import wraps
import openai
import random
from bson.json_util import dumps
import requests
import time
from requests.exceptions import HTTPError, Timeout, RequestException
import logging
import json


load_dotenv()
app = Flask(__name__, template_folder='.')
openai.api_key = os.getenv("OPENAI_API_KEY")
app.secret_key=os.getenv("Secret_key")
app.wsgi_app = DebuggedApplication(app.wsgi_app, True)  
url=os.getenv("DATABASE_URL")
client = MongoClient(url)
hf_api_key=os.getenv('HUGGINGFACE_API_KEY')
HUGGINGFACE_API_URL = "https://api-inference.huggingface.co/models/runwayml/stable-diffusion-v1-5"


db = client.get_database("Languify")
collection = db["products"]
User_collection = db["users"]
Point_collection = db["points"]
PointsHistory_collection=db["point_history"]

class User:
    def __init__(self, username, email, password,mother_language,level=None,privilige=None,status=None,wanted_language=None):
        self.user_id = str(uuid.uuid4())
        self.username = username
        self.email = email
        self.password = generate_password_hash(password)
        self.mother_language=mother_language
        self.level = level if level else "beginner"
        self.privilage=privilige if privilige  else "User" 
        self.status=status if status else "Basic"
        self.wanted_language = wanted_language




class Points:
    def __init__(self, user_id, points,last_date):
        self.points_id = str(uuid.uuid4())
        self.user_id = user_id
        self.points = points
        self.last_date=last_date

class PointsHistory:
    def __init__(self, user_id, points_earned, date_earned):
        self.history_id = str(uuid.uuid4())
        self.user_id = user_id
        self.points_earned = points_earned
        self.date_earned = date_earned




def auth_middleware(route_handler):
    @wraps(route_handler)
    def wrapper(*args, **kwargs):
        token = request.cookies.get('token')
        if not token:
            flash('Authentication token missing', 'failure')
            return redirect('/sign_in')

        try:
            decoded_token = jwt.decode(token, app.secret_key, algorithms=['HS256'])
        except jwt.ExpiredSignatureError:
            flash('Token expired', 'failure')
            return redirect('/sign_in')
        except jwt.InvalidTokenError:
            flash('you are not autherized to access that!', 'failure')
            return redirect('/sign_in')

        return route_handler(*args, **kwargs)

    return wrapper
def privilege_middleware(route_handler):
    @wraps(route_handler)
    def wrapper(*args, **kwargs):
        # Retrieve the user_id from the session
        user_id = session.get('user_id')

        # If user_id is not in session, redirect to sign-in page
        if not user_id:
            flash('User not logged in', 'failure')
            return redirect('/sign_in')

        # Assuming you have a function to retrieve the user's role based on user_id
       
        user = User_collection.find_one({'user_id': user_id})
        user_role = user.get('privilage')
        # If the user is not an admin, redirect with a flash message
        if user_role != 'admin':
            flash('You are not authorized to access this resource', 'failure')
            return redirect('/')

        # If the user is an admin, proceed to the route handler
        return route_handler(*args, **kwargs)

    return wrapper

@app.route('/signup', methods=['POST'])
def signup():
    username = request.form.get('username')
    email = request.form.get('email')
    password = request.form.get('password')
    mother_language= request.form.get('mother_language')
    if not username or not email or not password or not mother_language:
        return jsonify({'message': 'Username, email, and password are required fields'}), 400
  
    # Check if the user already exists
    existing_user = User_collection.find_one({'email': email})
    if existing_user:
        flash('User already exists', 'failure')
        return redirect('/sign_up')
    
    new_user = User(username, email, password,mother_language)
    new_points = Points(user_id=new_user.user_id, points=0, last_date=datetime.now())
    Point_collection.insert_one(new_points.__dict__)
    User_collection.insert_one(new_user.__dict__)
    token = jwt.encode({'email': email}, app.secret_key, algorithm='HS256')
    response = make_response(redirect('/'))
    response.set_cookie('user_id', str(new_user.user_id))  
    response.set_cookie('token', token)
    flash(f'Welcome, {username}! You have successfully signed up.', 'success')

    return response
@app.route('/signin', methods=['POST'])
def signin():
    email = request.form.get('email')
    password = request.form.get('password')

    if not email or not password:
        flash('Email and password are required fields', 'failure')
        return redirect('/sign_in')

    user = User_collection.find_one({'email': email})
    if not user or not check_password_hash(user['password'], password):
        flash('Invalid email or password', 'failure')
        return redirect('/sign_in')
    
    token = jwt.encode({'email': email}, app.secret_key, algorithm='HS256')
    response = make_response(redirect('/'))
    response.set_cookie('user_id', str(user.get('user_id')))  # Set user_id as a cookie

    response.set_cookie('token', token)

    flash('Welcome back!', 'success')
    return response

@app.route('/logout')
def logout():
    response = make_response(redirect(url_for('sign_in')))
    response.set_cookie('token', expires=0)  
    response.set_cookie('user_id', expires=0)  

    return response

@app.route('/add_point', methods=['POST'])
def add_point():
    if 'user_id' not in session:
        flash('not authrized!', 'failure')
        return redirect('/sign_in')
    user_id = session['user_id']
    user = User_collection.find_one({'user_id': user_id})
    if not user:
        return jsonify({'message': 'User not found'}), 404
    user_points = user.get('points', 0)
    user_points += 1  
    User_collection.update_one({'user_id': user_id}, {'$set': {'points': user_points}})
    new_point_history = PointsHistory(user_id=user_id, points_earned=1, date_earned=datetime.now())
    PointsHistory_collection.insert_one(new_point_history.__dict__)

    return jsonify({'message': 'Point added successfully'}), 200
@app.route('/api/users/update_wanted_language/<user_id>', methods=['POST'])
def update_wanted_language(user_id):
    # Get the new wanted language from the request data
    new_wanted_language = request.json.get('wanted_language')

    # Find the user by user_id
    user = User_collection.find_one({'user_id': user_id})
    if not user:
        return jsonify({'error': 'User not found'}), 404

    # Update the wanted language for the user
    User_collection.update_one({'user_id': user_id}, {'$set': {'wanted_language': new_wanted_language}})

    # Return success message
    response = make_response(jsonify({'message': 'Wanted language updated successfully', 'new_wanted_language': new_wanted_language}))
    response.set_cookie('wanted_language', value=new_wanted_language, max_age=302460*60)  # Expires in 30 days

    return response

@app.route('/')
@auth_middleware
def index():
    return render_template('front.html')

    
@app.route('/sign_in')
def sign_in():
    return render_template('sign-in.html')
@app.route('/sign_up')
def sign_up():
    return render_template('sign-up.html')
@app.route('/image')
def image():
    return render_template('image.html')
@app.route('/words')
def words():
    return render_template('words.html')
@app.route('/paragraph_tts')
def paragraph_tts():
    return render_template('paragraph_tts.html')
@app.route('/audio_words')
def audio_words():
    return render_template('audio_words.html')
@app.route('/test')
def test():
    return render_template('test.html')
@app.route('/chat')
def chat():
    return render_template('chat.html')
@app.route('/describe_img')
def describe_img():
    return render_template('describe_img.html')
@app.route('/profile')
def profile():
    return render_template('profile.html')


#generate sentence
@app.route('/generate_sentence')
def generate_sentence():
    headers = {
        'Authorization': f'Bearer {openai.api_key}',
        'Content-Type': 'application/json',
    }
    data = {
        "model": "gpt-3.5-turbo",
        "messages": [
            {"role": "system", "content": "Generate a random sentence with 6 to 8 words."},
            {"role": "user", "content": "Give me a random sentence that has between 6 to 8 words. DO NOT INCLUDE ANY OTHER TEXT, GIVE ME JUST THE SENTENCE."}
        ]
    }

    try:
        response = requests.post('https://api.openai.com/v1/chat/completions', headers=headers, json=data)
        if response.status_code == 200:
            response_data = response.json()
            sentence = response_data['choices'][0]['message']['content'].strip()
            words = sentence.split()
            if 6 <= len(words) <= 8:  # Ensure the sentence has between 6 to 8 words
                random.shuffle(words)  # Shuffle the words to create the game challenge
                return jsonify({'original': sentence, 'shuffled': words}), 200
            else:
                return jsonify({'error': 'Generated sentence does not meet the word count requirement.'}), 400
        else:
            return jsonify({'error': 'Failed to fetch response from OpenAI'}), response.status_code
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/update_points', methods=['POST'])
def update_points():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'User not authenticated'}), 401

    user = User_collection.find_one({'user_id': user_id})
    if not user:
        return jsonify({'error': 'User not found'}), 404

    # Increment the user's points in the User collection.
    new_points = user.get('points', 0) + 1
    User_collection.update_one({'user_id': user_id}, {'$set': {'points': new_points}})

    # Check if a points document already exists for this user.
    points_document = Point_collection.find_one({'user_id': user_id})
    if points_document:
        # If it exists, update the points and last updated date.
        Point_collection.update_one(
            {'user_id': user_id},
            {'$set': {'points': new_points, 'last_date': datetime.now()}}
        )
    else:
        # If no document exists, create a new one.
        new_points_document = {
            'user_id': user_id,
            'points': new_points,
            'last_date': datetime.now()
        }
        Point_collection.insert_one(new_points_document)

    points_history_entry = PointsHistory(user_id=user_id, points_earned=1, date_earned=datetime.now())
    PointsHistory_collection.insert_one(points_history_entry.__dict__)
 
    if new_points >= 50:
        # Logic to handle advanced level or difficulty increase.
        User_collection.update_one({'user_id': user_id}, {'$set': {'level': 'advanced'}})

    return jsonify({'message': 'Points updated successfully', 'points': new_points})
@app.route('/change_status', methods=['POST'])
def change_status():
    if 'user_id' not in session:
        flash('not authrized!', 'failure')
        return redirect('/sign_in')
    user_id = session['user_id']
    user = User_collection.find_one({'user_id': user_id})
    if not user:
        return jsonify({'message': 'User not found'}), 404
    User_collection.update_one({'user_id': user_id}, {'$set': {'status': 'premium'}})
    flash('Plan upgraded!', 'success')
    return jsonify({'message': 'Point added successfully'}), 200

@app.route('/api/users/<user_id>', methods=['GET'])
def get_user(user_id):
    # Perform an aggregation to join the user data with their point history
    pipeline = [
        {"$match": {"user_id": user_id}},  # Match the user by user_id
        {
            "$lookup": {
                "from": "points_history",  # The collection to join with
                "localField": "user_id",  # Field from the "users" collection
                "foreignField": "user_id",  # Field from the "points_history" collection
                "as": "point_history"  # Alias for the joined documents
            }
        },
        {
            "$lookup": {
                "from": "points",  # The collection to join with
                "localField": "user_id",  # Field from the "users" collection
                "foreignField": "user_id",  # Field from the "points" collection
                "as": "points"  # Alias for the joined documents
            }
        }
    ]

    # Execute the aggregation pipeline
    user_data = list(User_collection.aggregate(pipeline))

    # Check if the user exists
    if user_data:
        # Extract level from the user data
        level = user_data[0].get('level', 'beginner')

        # Convert the result to JSON
        user_json = dumps(user_data[0])

        # Create response with user data
        response = make_response(jsonify(user_json))

        # Set the level in a cookie
        response.set_cookie('level', value=level, max_age=302460*60)  # Expires in 30 days

        return response
    else:
        return jsonify({'message': 'User not found'}), 404
    
@app.route('/api/openai/completion', methods=['POST'])
def openai_completion():
    # Get the prompt from the request
    prompt = request.json.get('prompt')
    engine = request.json.get('engine', "gpt-3.5-turbo")
    max_tokens = request.json.get('max_tokens', 50)
    
    # Make the completion request
    response = openai.Completion.create(
        engine=engine,
        prompt=prompt,
        max_tokens=max_tokens
    )
    print(response)
    return jsonify({'response': response.choices[0].text.strip()})

#chatbot code:
# Initialize a simple in-memory structure to hold conversation histories
# In a production environment, consider using a more persistent storage solution
conversations = {}


def get_conversation_history(session_id):
    return conversations.get(session_id, [])

def update_conversation_history(session_id, user_message, bot_message):
    if session_id not in conversations:
        conversations[session_id] = []
    conversations[session_id].append({"role": "user", "content": user_message})
    conversations[session_id].append({"role": "assistant", "content": bot_message})

def create_prompt_with_instructions(messages, instruction="Respond with short, engaging messages. Ask questions or suggest topics to keep the conversation going."):
    """
    Prepares a prompt with instructions for the model to follow, ensuring the responses are not only brief but also engaging and interactive.
    
    :param messages: The conversation history as a list of message dictionaries.
    :param instruction: A string containing the instruction for the model.
    :return: A list of messages including the instruction.
    """
    # Add the instruction as the first message from the system
    prompt_messages = [{"role": "system", "content": instruction}] + messages
    return prompt_messages


def suggest_topic_if_new_conversation(messages):
    """
    Suggests a topic if it's the beginning of a new conversation.
    
    :param messages: The conversation history as a list of message dictionaries.
    :return: The potentially modified list of messages with a suggested topic added if it's a new conversation.
    """
    topics = [
        "Would you like to talk about 'technology and its impacts on society'?",
        "How about discussing 'the future of space exploration'?",
        "What are your thoughts on 'artificial intelligence and ethics'?",
        "Let's consider 'the importance of environmental conservation'.",
        "Are you interested in 'the evolution of music genres over the decades'?",
        "What do you think about 'the role of social media in modern communication'?"
    ]
    
    if not messages:  # If it's a new conversation
        default_topic_instruction = random.choice(topics)
        messages.insert(0, {"role": "system", "content": default_topic_instruction})
    return messages

@app.route('/ask', methods=['POST'])
def ask():
    headers = {
    'Authorization': f'Bearer {openai.api_key}',
    'Content-Type': 'application/json',
    }
    data = request.json
    session_id = data.get('session_id')  # A unique session identifier from the client
    user_message = data['message']
    
    # Retrieve the existing conversation history
    conversation_history = get_conversation_history(session_id)
    
    # If it's a new conversation, suggest a topic
    conversation_history = suggest_topic_if_new_conversation(conversation_history)

    # Add an instruction for the model to keep responses interactive
    prompt_messages = create_prompt_with_instructions(conversation_history + [{"role": "user", "content": user_message}])

    data = {
        "model": "gpt-3.5-turbo",
        "messages": prompt_messages,
    }

    response = requests.post('https://api.openai.com/v1/chat/completions', headers=headers, json=data)
    
    if response.status_code == 200:
        response_data = response.json()
        bot_message = response_data['choices'][0]['message']['content']
        
        # Update the conversation history with the latest exchange, including any system message
        update_conversation_history(session_id, user_message, bot_message)
        
        return jsonify({'response': bot_message.strip()}), 200
    else:
        return jsonify({'error': 'Failed to fetch response from OpenAI'}), response.status_code

#generate image with words
def query_image_generation(prompt, retry_limit=3, timeout=10):
    hf_headers = {"Authorization": f"Bearer {hf_api_key}"}
    data = {"inputs": prompt}
    for attempt in range(retry_limit):
        try:
            response = requests.post(HUGGINGFACE_API_URL, headers=hf_headers, json=data, timeout=timeout)
            response.raise_for_status()
            return response.content
        except Timeout:
            logging.warning('The request timed out, attempting retry...')
        except HTTPError as http_err:
            if response.status_code == 503 and attempt < retry_limit - 1:
                logging.warning('Service unavailable, retrying...')
            else:
                logging.error(f'HTTP error occurred: {http_err}')
                break
        except RequestException as req_err:
            logging.error(f'Request error occurred: {req_err}')
            break
        time.sleep((2 ** attempt) * 3)
    return None

@app.route('/generate_image_with_random_word')
def generate_image_with_random_word():
    headers = {
        'Authorization': f'Bearer {openai.api_key}',
        'Content-Type': 'application/json',
    }
    data = {
        "model": "gpt-3.5-turbo",
        "messages": [
            {"role": "system", "content": "Generate 4 random words that can be visually represented. DO NOT INCLUDE ANY ADDITIONAL CHARACTERS OR SYMBOLS. DO NOT ENUMERATE THE WORDS. MAKE SURE TO ALWAYS GIVE THE WORDS IN THIS FORMAT: 'word1\nword2\nword3\nword4'."}
        ]
    }
    try:
        response = requests.post('https://api.openai.com/v1/chat/completions', headers=headers, json=data)
        response.raise_for_status()
        words = response.json()['choices'][0]['message']['content'].strip().split("\n")
        object_name = random.choice(words)
        prompt = f"Generate an image of {object_name}"
        image_data = query_image_generation(prompt)
        if image_data:
            file_path = './static/img/generated_image.png'
            with open(file_path, 'wb') as f:
                f.write(image_data)
            return jsonify({'message': 'Image generated successfully', 'words': words, 'correct_word': object_name})
        else:
            return jsonify({'message': 'Failed to generate image'})
    except Exception as e:
        logging.error(f'Error occurred: {e}')
        return jsonify({'message': 'Failed to generate image. Internal server error.'})

@app.route('/generate_words_for_tts')
def generate_words_for_tts():
    headers = {
        'Authorization': f'Bearer {openai.api_key}',
        'Content-Type': 'application/json',
    }
    data = {
        "model": "gpt-3.5-turbo",
        "messages": [
            {"role": "system", "content": "Generate 4 random words that are close in pronunciation but not too much in English. DO NOT INCLUDE ANY ADDITIONAL CHARACTERS OR SYMBOLS. DO NOT ENUMERATE THE WORDS. MAKE SURE TO ALWAYS GIVE THE WORDS IN THIS FORMAT: 'word1\nword2\nword3\nword4'."}
        ]
    }
    try:
        response = requests.post('https://api.openai.com/v1/chat/completions', headers=headers, json=data)
        response.raise_for_status()  
        words = response.json()['choices'][0]['message']['content'].strip().split("\n")
        correct_word = random.choice(words)
        return jsonify({'words': words, 'correct_word': correct_word})
    except Exception as e:
        logging.error(f'Error occurred: {e}')
        return jsonify({'error': str(e)}), 500
    

    
@app.route('/generate_paragraph_for_tts')
def generate_paragraph_for_tts():
    headers = {
        'Authorization': f'Bearer {openai.api_key}',
        'Content-Type': 'application/json',
    }
    data = {
        "model": "gpt-3.5-turbo",
        "messages": [
            {"role": "system", "content": "Generate a random sentence suitable for language learning. The sentence should be easy to understand and pronounce for English speakers. DO NOT INCLUDE ANY ADDITIONAL CHARACTERS OR SYMBOLS like '.', ',', '?', etc."}
        ]
    }
    try:
        response = requests.post('https://api.openai.com/v1/chat/completions', headers=headers, json=data)
        response.raise_for_status() 
        paragraph = response.json()['choices'][0]['message']['content'].strip()
        return jsonify({'paragraph': paragraph})
    except Exception as e:
        logging.error(f'Error occurred: {e}')
        return jsonify({'error': str(e)}), 500
    

#for quiz "test"
@app.route('/expand_on_topic', methods=['POST'])
def expand_on_topic():
    headers = {
        'Authorization': f'Bearer {openai.api_key}',
        'Content-Type': 'application/json',
    }
    prompt = request.json.get('prompt')
    data = {
        "model": "gpt-3.5-turbo",
        "messages": [
            {"role": "system", "content": "Expand on a Topic provided by the user."},
            {"role": "user", "content": prompt}
        ]
    }
    try:
        response = requests.post('https://api.openai.com/v1/chat/completions', headers=headers, json=data)
        response.raise_for_status()
        sentence = response.json()['choices'][0]['message']['content'].strip()
        return jsonify({'original': sentence})
    except Exception as e:
        logging.error(f'Error occurred: {e}')
        return jsonify({'error': str(e)}), 500
    
@app.route('/generate_multiple_choice_questions', methods=['POST'])
def generate_multiple_choice_questions():
    headers = {
        'Authorization': f'Bearer {openai.api_key}',
        'Content-Type': 'application/json',
    }
    topic = request.json.get('topic')
    data = {
        "model": "gpt-3.5-turbo",
        "messages": [
            {"role": "system", "content": f"Generate 4 multiple-choice questions based on the text: {topic}."}
        ]
    }
    try:
        response = requests.post('https://api.openai.com/v1/chat/completions', headers=headers, json=data)
        response.raise_for_status()  # Check for HTTP request errors
        
        # The response data should directly give you the text containing questions
        questions_untreated = response.json()['choices'][0]['message']['content'].strip()
        
        # Since the questions are expected to be formatted as a single string with questions split by two newlines, we don't need further processing
        questions = questions_untreated.split('\n\n')  # Splitting by two newlines to separate each question

        return jsonify({'questions': questions})

    except Exception as e:
        logging.error(f'Error occurred: {e}')
        return jsonify({'error': str(e)}), 500
    
def generate_prompt(selected_options):
    prompt = "Given the provided questions, create a JSON object which enumerates a set of 4 child objects.Each child object has a property named 'question' and a property named 'answer' and a property named 'user_answer'.For each child object assign to the property named 'question' a questions provided and to the property named 'answer' the correct answer to the question to the property named 'answer_user' allovate the answer provided from the user .The resulting JSON object should be in this format: [{'question':'string','answer':'string'}].\n\n"
    
    for idx, option in enumerate(selected_options, start=1):
        question = option['question']
        selected_option_index = option['selectedOptionIndex']
        options = option['options']
        
        prompt += f"{idx}. {question}\n"
        for i, opt in enumerate(options):
            if i == selected_option_index:
                prompt += f"[{chr(ord('A') + i)}] {opt} (User's Choice)\n"
            else:
                prompt += f"[{chr(ord('A') + i)}] {opt}\n"
    return prompt

@app.route('/submit_test', methods=['POST'])
def submit_test():
    selected_options = request.json.get('selectedOptions', [])
    prompt = generate_prompt(selected_options)  
    headers = {
        'Authorization': f'Bearer {openai.api_key}',
        'Content-Type': 'application/json',
    }
    data = {
        "model": "gpt-3.5-turbo",
        "messages": [
            {"role": "system", "content": prompt}
        ]
    }
    try:
        response = requests.post('https://api.openai.com/v1/chat/completions', headers=headers, json=data)
        response.raise_for_status() 
        evaluation_result = response.json()['choices'][0]['message']['content'].strip()
        evaluation_result_list = json.loads(evaluation_result.replace("'", '"'))
        return jsonify({'message': 'Test submitted successfully', 'evaluation_result': evaluation_result_list}), 200
    except Exception as e:
        logging.error(f'Error occurred: {e}')
        return jsonify({'error': str(e)}), 500
    
#describe image from url
@app.route('/analyze-image-url', methods=['POST'])
def analyze_image_url():
    data = request.get_json()
    image_url = data.get('image_url')
    
    if not image_url:
        return jsonify({'error': 'No image URL provided'}), 400

    headers = {
        'Authorization': f'Bearer {openai.api_key}',
        'Content-Type': 'application/json',
    }
    data ={
        "model": "gpt-4-vision-preview",
        "messages": [
            {
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe this image briefely."},
                {
                "type": "image_url",
                "image_url": {
                    "url": image_url,
                },
                },
            ],
            }
        ],
        "max_tokens" : 300
    }
    try:
        response = requests.post('https://api.openai.com/v1/chat/completions', headers=headers, json=data)
        if response.ok:
            response_data = response.json()
            description = response_data['choices'][0]['message']['content']
            return jsonify({'description': description})
        else:
            return jsonify({'error': 'Failed to fetch response from OpenAI', 'status_code': response.status_code})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)