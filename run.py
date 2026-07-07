import os
from app import create_app

app = create_app()

if __name__ == "__main__":
    # Ensure SECRET_KEY is set to prevent session invalidation on restart
    if not os.environ.get("SECRET_KEY"):
        os.environ["SECRET_KEY"] = "dev-secret-key"
        app.config["SECRET_KEY"] = "dev-secret-key"

    # Exclude workspace directory from triggering reloads
    app.run(debug=True, exclude_patterns=["workspace/*", "workspace/**"])
