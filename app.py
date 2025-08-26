import os
import mysql.connector
from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "supersecretkey"

# Upload config
app.config['UPLOAD_FOLDER'] = 'static/uploads/recipes'

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Make sure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# MySQL connection
# mydb = mysql.connector.connect(
#     host="localhost",
#     user="root",           
#     password="Munny1@@@",  
#     database="recipes"
# )
# if not mydb.is_connected():
#     mydb.reconnect()

from urllib.parse import urlparse

# Get the DATABASE_URL from environment
db_url = os.environ.get("railway")
if db_url is None:
    raise Exception("DATABASE_URL not found in environment variables")

# Parse the URL
url = urlparse(db_url)

mydb = mysql.connector.connect(
    host=url.hostname,
    port=url.port,
    user=url.username,
    password=url.password,
    database=url.path[1:]  # remove leading '/'
)


@app.route("/")
def index():
    return render_template("index.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        email = request.form["email"]
        password = request.form["password"]

        cursor = mydb.cursor(buffered=True)

        # Check if email already exists
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        existing_user = cursor.fetchone()

        if existing_user:
            flash("⚠️ Email already exists, please login!", "error")
            cursor.close()
            return redirect(url_for("register"))

        # Hash the password
        hashed_password = generate_password_hash(password)

        try:
            cursor.execute(
                "INSERT INTO users (username, email, password) VALUES (%s, %s, %s)",
                (username, email, hashed_password)
            )
            mydb.commit()
            flash("✅ Registration successful! Please login.", "success")
            return redirect(url_for("index"))
        except mysql.connector.Error as err:
            flash(f"Database Error: {err}", "error")
        finally:
            cursor.close()

    return render_template("register.html")

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        cursor = mydb.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cursor.fetchone()

        if user:
            if check_password_hash(user['password'], password):
                session['user'] = user['username']
                flash("Login successful!", "success")
                return redirect(url_for('dashboard'))
            else:
                flash("Incorrect password. Please try again.", "error")
        else:
            flash("No user found with that username.", "error")

    return render_template("login.html")

@app.route('/dashboard')
def dashboard():
    if not session.get('user'):
        flash("Please log in to access the dashboard.", "error")
        return redirect(url_for('login'))

    cursor = mydb.cursor(dictionary=True)

    # Get logged-in user info
    cursor.execute("SELECT id, username FROM users WHERE username=%s", [session['user']])
    user_data = cursor.fetchone()

    # Get user's recipes
    cursor.execute("SELECT * FROM recipes WHERE added_by=%s", [user_data['id']])
    my_recipes = cursor.fetchall()

    # Get all other recipes
    cursor.execute("SELECT r.*, u.username FROM recipes r JOIN users u ON r.added_by=u.id WHERE r.added_by!=%s", [user_data['id']])
    other_recipes = cursor.fetchall()

    cursor.close()

    return render_template(
        "dashboard.html",
        user_data=user_data,
        my_recipes=my_recipes,
        other_recipes=other_recipes
    )


@app.route('/add_recipe', methods=['GET', 'POST'])
def add_recipe():
    if not session.get('user'):
        flash("Please log in to add recipes.", "error")
        return redirect(url_for('login'))

    if request.method == 'POST':
        title = request.form.get('title')
        ingredients = request.form.get('ingredients')
        instructions = request.form.get('instructions')
        category = request.form.get('category')
        if category:
            category = category.capitalize()
        image = request.files.get('image')

        # Debug prints
        print("Form data received:")
        print("Title:", title)
        print("Ingredients:", ingredients)
        print("Instructions:", instructions)
        print("Category:", category)
        print("Image filename:", image.filename if image else "No image")

        # Validate form fields
        if not title or not ingredients or not instructions or not category:
            flash('Please fill out all fields.', 'error')
            return redirect(url_for('add_recipe'))

        image_filename = None
        if image and allowed_file(image.filename):
            filename = secure_filename(image.filename)
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            # Save the image
            image.save(image_path)
            image_filename = filename
        else:
            flash('Invalid image format. Allowed types: png, jpg, jpeg, gif.', 'error')
            return redirect(url_for('add_recipe'))

        cursor = mydb.cursor()

        # Get user id for added_by using session['user']
        cursor.execute("SELECT id FROM users WHERE username=%s", (session['user'],))
        user = cursor.fetchone()
        if not user:
            cursor.close()
            flash('User not found.', 'error')
            return redirect(url_for('login'))

        try:
            cursor.execute(
                "INSERT INTO recipes (title, ingredients, instructions, image, category, added_by) VALUES (%s, %s, %s, %s, %s, %s)",
                (title, ingredients, instructions, image_filename, category, user[0])
            )
            mydb.commit()
            flash('Recipe added successfully!', 'success')
            return redirect(url_for('dashboard'))
        except mysql.connector.Error as err:
            flash(f'Database Error: {err}', 'error')
        finally:
            cursor.close()

    # GET request
    return render_template('add_recipe.html')


@app.route('/browse')
def browse():
    if not session.get('user'):
        flash("Please log in to browse recipes.", "error")
        return redirect(url_for('login'))

    cursor = mydb.cursor(dictionary=True)
    # Get all recipes with their authors' usernames
    cursor.execute("""
        SELECT r.id, r.title, r.image, u.username
        FROM recipes r
        JOIN users u ON r.added_by = u.id
        ORDER BY r.id DESC
    """)
    recipes = cursor.fetchall()
    cursor.close()

    return render_template('browse.html', recipes=recipes)


@app.route('/recipe/<int:recipe_id>')
def view_recipe(recipe_id):
    if not session.get('user'):
        flash("Please log in to view recipes.", "error")
        return redirect(url_for('login'))

    cursor = mydb.cursor(dictionary=True)
    cursor.execute("""
        SELECT r.*, u.username 
        FROM recipes r 
        JOIN users u ON r.added_by = u.id 
        WHERE r.id = %s
    """, (recipe_id,))
    recipe = cursor.fetchone()
    cursor.close()

    if not recipe:
        flash("Recipe not found.", "error")
        return redirect(url_for('browse'))

    return render_template('view_recipe.html', recipe=recipe)

@app.route('/my_recipe')  # or rename to '/my_recipes' everywhere for consistency
def my_recipe():
    if not session.get('user'):
        flash("Please log in to view your recipes.", "error")
        return redirect(url_for('login'))

    cursor = mydb.cursor(dictionary=True)
    cursor.execute("SELECT id FROM users WHERE username=%s", (session['user'],))
    user = cursor.fetchone()
    if not user:
        cursor.close()
        flash("User not found.", "error")
        return redirect(url_for('login'))

    cursor.execute("""
        SELECT id, title, image
        FROM recipes
        WHERE added_by = %s
        ORDER BY id DESC
    """, (user['id'],))
    recipes = cursor.fetchall()
    cursor.close()

    return render_template('my_recipe.html', recipes=recipes)
    if not session.get('user'):
        flash("Please log in to view your recipes.", "error")
        return redirect(url_for('login'))

    cursor = mydb.cursor(dictionary=True)
    # Get logged-in user's id
    cursor.execute("SELECT id FROM users WHERE username=%s", (session['user'],))
    user = cursor.fetchone()
    if not user:
        cursor.close()
        flash("User not found.", "error")
        return redirect(url_for('login'))

    # Get recipes added by the user
    cursor.execute("""
        SELECT id, title, image
        FROM recipes
        WHERE added_by = %s
        ORDER BY id DESC
    """, (user['id'],))
    recipes = cursor.fetchall()
    cursor.close()

    return render_template('my_recipe.html', recipes=recipes)

@app.route('/edit_recipe/<int:recipe_id>', methods=['GET', 'POST'])
def edit_recipe(recipe_id):
    if not session.get('user'):
        flash("Please log in to edit recipes.", "error")
        return redirect(url_for('login'))

    cursor = mydb.cursor(dictionary=True)
    # Verify ownership
    cursor.execute("SELECT id FROM users WHERE username=%s", (session['user'],))
    user = cursor.fetchone()
    if not user:
        cursor.close()
        flash("User not found.", "error")
        return redirect(url_for('login'))

    cursor.execute("SELECT * FROM recipes WHERE id=%s AND added_by=%s", (recipe_id, user['id']))
    recipe = cursor.fetchone()
    if not recipe:
        cursor.close()
        flash("Recipe not found or you don't have permission to edit.", "error")
        return redirect(url_for('my_recipes'))

    if request.method == "POST":
        title = request.form.get('title')
        ingredients = request.form.get('ingredients')
        instructions = request.form.get('instructions')
        image = request.files.get('image')

        if not title or not ingredients or not instructions:
            flash('All fields except image are required.', 'error')
            cursor.close()
            return redirect(url_for('edit_recipe', recipe_id=recipe_id))

        image_filename = recipe['image']  # keep old image by default
        if image and allowed_file(image.filename):
            filename = secure_filename(image.filename)
            image.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            image_filename = filename
        elif image and image.filename != '':
            flash('Invalid image format.', 'error')
            cursor.close()
            return redirect(url_for('edit_recipe', recipe_id=recipe_id))

        try:
            cursor.execute("""
                UPDATE recipes SET title=%s, ingredients=%s, instructions=%s, image=%s WHERE id=%s
            """, (title, ingredients, instructions, image_filename, recipe_id))
            mydb.commit()
            flash('Recipe updated successfully.', 'success')
            cursor.close()
            return redirect(url_for('my_recipe'))
        except mysql.connector.Error as err:
            flash(f'Database Error: {err}', 'error')
            cursor.close()
            return redirect(url_for('edit_recipe', recipe_id=recipe_id))

    cursor.close()
    # Render edit form prefilled with recipe data
    return render_template('edit_recipe.html', recipe=recipe)

@app.route('/category/<category_name>')
def category_view(category_name):
    if not session.get('user'):
        flash("Please log in to view recipes.", "error")
        return redirect(url_for('login'))

    cursor = mydb.cursor(dictionary=True)
    # Capitalize category to match database values if needed
    category = category_name.capitalize()
    cursor.execute("""
        SELECT r.*, u.username 
        FROM recipes r 
        JOIN users u ON r.added_by = u.id 
        WHERE r.category = %s
        ORDER BY r.id DESC
    """, (category,))
    recipes = cursor.fetchall()
    cursor.close()

    return render_template('category.html', recipes=recipes, category=category)


@app.route('/delete_recipe/<int:recipe_id>', methods=['POST'])
def delete_recipe(recipe_id):
    if not session.get('user'):
        flash("Please log in to delete recipes.", "error")
        return redirect(url_for('login'))

    cursor = mydb.cursor(dictionary=True)
    cursor.execute("SELECT id FROM users WHERE username=%s", (session['user'],))
    user = cursor.fetchone()
    if not user:
        cursor.close()
        flash("User not found.", "error")
        return redirect(url_for('login'))

    # Confirm ownership before deleting
    cursor.execute("SELECT * FROM recipes WHERE id=%s AND added_by=%s", (recipe_id, user['id']))
    recipe = cursor.fetchone()
    if not recipe:
        cursor.close()
        flash("Recipe not found or you don't have permission to delete.", "error")
        return redirect(url_for('my_recipe'))

    try:
        cursor.execute("DELETE FROM recipes WHERE id=%s", (recipe_id,))
        mydb.commit()
        flash("Recipe deleted successfully.", "success")
    except mysql.connector.Error as err:
        flash(f"Database Error: {err}", "error")
    finally:
        cursor.close()

    return redirect(url_for('my_recipe'))


@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for('login'))


@app.route('/delete_account', methods=['POST'])
def delete_account():
    if not session.get('user'):
        flash("Please log in to delete your account.", "error")
        return redirect(url_for('login'))

    cursor = mydb.cursor(dictionary=True)

    # Get user id
    cursor.execute("SELECT id FROM users WHERE username=%s", (session['user'],))
    user = cursor.fetchone()

    if not user:
        cursor.close()
        flash("User not found.", "error")
        return redirect(url_for('login'))

    user_id = user['id']

    try:
        # Delete all user's recipes first (to avoid foreign key constraint issues)
        cursor.execute("DELETE FROM recipes WHERE added_by=%s", (user_id,))
        # Then delete user account
        cursor.execute("DELETE FROM users WHERE id=%s", (user_id,))
        mydb.commit()
        session.clear()
        flash("Your account and all associated recipes have been deleted.", "success")
        cursor.close()
        return redirect(url_for('index'))
    except mysql.connector.Error as err:
        flash(f"Database Error: {err}", "error")
        cursor.close()
        return redirect(url_for('my_recipes'))


if __name__ == "__main__":
    app.run(debug=True)
