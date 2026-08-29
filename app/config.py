import os


class Config:
    """Base configuration."""
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-12345')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    ENABLE_DIAGNOSTICS = (
        os.getenv("ENABLE_DIAGNOSTICS", "false").lower() == "true"
    )

    # Use workspace folder for database
    BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        f'sqlite:///{os.path.join(BASE_DIR, "hockey.db")}'
    )


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    ENABLE_DIAGNOSTICS = True


class TestingConfig(Config):
    """Testing configuration."""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False

    # In production, we require a stronger secret key
    SECRET_KEY = os.environ.get('SECRET_KEY')

config_by_name = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
