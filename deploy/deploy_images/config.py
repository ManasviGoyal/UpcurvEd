# deploy/deploy_images/config.py
"""
Centralized configuration for container image building and pushing.
Update these values for your specific GCP project and environment.

For production: Override via Pulumi config (pulumi config set) or environment variables.
"""

# GCP Project Configuration
import os

GCP_PROJECT_ID = os.environ.get("GCP_PROJECT", "ac215-project-475007")  # Centralized project ID
GCP_REGION = "us-central1"

# Docker Registry Configuration
ARTIFACT_REGISTRY_REPO = "ac215-group1-repository"

# Container Image Names
BACKEND_IMAGE_NAME = "ac215-backend-api"
FRONTEND_IMAGE_NAME = "ac215-frontend"
RAG_IMAGE_NAME = "ac215-rag-service"
