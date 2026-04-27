import datetime
import os

import pulumi
import pulumi_docker_build as docker_build
from config import (
    ARTIFACT_REGISTRY_REPO,
    BACKEND_IMAGE_NAME,
    FRONTEND_IMAGE_NAME,
    GCP_REGION,
    RAG_IMAGE_NAME,
)
from pulumi import CustomTimeouts
from pulumi_gcp import artifactregistry

# Get absolute paths for build contexts
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# Get project info
project = pulumi.Config("gcp").require("project")
location = GCP_REGION

# Timestamp for tagging
timestamp_tag = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
repository_name = ARTIFACT_REGISTRY_REPO
registry_url = f"{location}-docker.pkg.dev/{project}/{repository_name}"

# Create Artifact Registry repository if it doesn't exist
artifact_repo = artifactregistry.Repository(
    "artifact-registry-repo",
    repository_id=repository_name,
    location=location,
    format="DOCKER",
    description="Docker repository for AC215 Group 1 application images",
    opts=pulumi.ResourceOptions(
        protect=True,  # Set to True in production to prevent accidental deletion
    )
)

# Docker Build + Push -> Backend API Service
# Backend uses ROOT context (copies from backend/ directory in Dockerfile line 41)
backend_service_image = docker_build.Image(
    f"build-{BACKEND_IMAGE_NAME}",
    tags=[pulumi.Output.concat(registry_url, "/", BACKEND_IMAGE_NAME, ":", timestamp_tag)],
    context=docker_build.BuildContextArgs(location=WORKSPACE_ROOT),  # ROOT context
    dockerfile=docker_build.DockerfileArgs(location=os.path.join(WORKSPACE_ROOT, "backend", "Dockerfile")),
    platforms=[docker_build.Platform.LINUX_AMD64],
    push=True,
    opts=pulumi.ResourceOptions(
        depends_on=[artifact_repo],  # Wait for registry to be created
        custom_timeouts=CustomTimeouts(create="30m"),
        retain_on_delete=True
    )
)
# Export references to stack
pulumi.export(f"{BACKEND_IMAGE_NAME}-ref", backend_service_image.ref)
pulumi.export(f"{BACKEND_IMAGE_NAME}-tags", backend_service_image.tags)

# Docker Build + Push -> Frontend
# Frontend uses its own directory as context (Dockerfile uses COPY . .)
frontend_image = docker_build.Image(
    f"build-{FRONTEND_IMAGE_NAME}",
    tags=[pulumi.Output.concat(registry_url, "/", FRONTEND_IMAGE_NAME, ":", timestamp_tag)],
    context=docker_build.BuildContextArgs(location=os.path.join(WORKSPACE_ROOT, "frontend")),
    dockerfile=docker_build.DockerfileArgs(location=os.path.join(WORKSPACE_ROOT, "frontend", "Dockerfile")),
    platforms=[docker_build.Platform.LINUX_AMD64],
    push=True,
    opts=pulumi.ResourceOptions(
        depends_on=[backend_service_image],  # Build sequentially to avoid overwhelming Docker
        custom_timeouts=CustomTimeouts(create="30m"),
        retain_on_delete=True
    )
)
pulumi.export(f"{FRONTEND_IMAGE_NAME}-ref", frontend_image.ref)
pulumi.export(f"{FRONTEND_IMAGE_NAME}-tags", frontend_image.tags)
# Docker Build + Push -> RAG Service
# RAG uses its own directory as context (Dockerfile uses COPY . .)
rag_service_image = docker_build.Image(
    f"build-{RAG_IMAGE_NAME}",
    tags=[pulumi.Output.concat(registry_url, "/", RAG_IMAGE_NAME, ":", timestamp_tag)],
    context=docker_build.BuildContextArgs(location=os.path.join(WORKSPACE_ROOT, "rag")),
    dockerfile=docker_build.DockerfileArgs(location=os.path.join(WORKSPACE_ROOT, "rag", "Dockerfile")),
    platforms=[docker_build.Platform.LINUX_AMD64],
    push=True,
    opts=pulumi.ResourceOptions(
        depends_on=[frontend_image],  # Build sequentially
        custom_timeouts=CustomTimeouts(create="30m"),
        retain_on_delete=True
    )
)
# Export references to stack
pulumi.export(f"{RAG_IMAGE_NAME}-ref", rag_service_image.ref)
pulumi.export(f"{RAG_IMAGE_NAME}-tags", rag_service_image.tags)

# Export additional info
pulumi.export("registry_url", registry_url)
pulumi.export("artifact_repository", artifact_repo.name)
