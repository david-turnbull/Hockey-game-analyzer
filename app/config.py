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


    ALLOW_PUBLIC_INGESTION = (
        os.getenv("ALLOW_PUBLIC_INGESTION", "true").lower() == "true"
    )
    ALLOW_PREDICTION_GENERATION = (
        os.getenv("ALLOW_PREDICTION_GENERATION", "false").lower() == "true"
    )
    PREDICTION_GENERATION_TOKEN = os.getenv("PREDICTION_GENERATION_TOKEN", "dev-gen-token-secret")


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True


class TestingConfig(Config):
    """Testing configuration."""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    ALLOW_PREDICTION_GENERATION = True
    PREDICTION_GENERATION_TOKEN = 'test-gen-token'


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False

    # In production, require environment-driven secret key
    SECRET_KEY = os.environ.get('SECRET_KEY')

    # Fail closed in production by default
    ALLOW_PUBLIC_INGESTION = (
        os.getenv("ALLOW_PUBLIC_INGESTION", "false").lower() == "true"
    )
    ALLOW_PREDICTION_GENERATION = (
        os.getenv("ALLOW_PREDICTION_GENERATION", "false").lower() == "true"
    )
    PREDICTION_GENERATION_TOKEN = os.environ.get("PREDICTION_GENERATION_TOKEN")

config_by_name = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
