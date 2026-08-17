import os
from app import create_app

# Default to development environment configuration
config_name = os.environ.get('FLASK_ENV', 'development')
app = create_app(config_name)

if __name__ == '__main__':
    # Run the application locally
    app.run(host='127.0.0.1', port=5000, debug=app.config.get('DEBUG', True))
