#!/bin/bash
set -e

REGISTRY="ghcr.io"
IMAGE_NAME="jules-dot-dev/story-manager-base"
DOCKERFILE_BASE="Dockerfile.base"
DOCKERFILE_APP="Dockerfile"

# Calculate the hash of the base Dockerfile
TAG=$(sha256sum "$DOCKERFILE_BASE" | cut -d' ' -f1)

# Log in to GitHub Container Registry (ensure you are logged in)
echo "Logging in to GitHub Container Registry..."
echo "$CR_PAT" | docker login "$REGISTRY" -u "$USERNAME" --password-stdin

# Check if the image already exists
if docker manifest inspect "$REGISTRY/$IMAGE_NAME:$TAG" > /dev/null; then
  echo "Image with tag $TAG already exists. Skipping build and push."
else
  echo "Image with tag $TAG not found. Building and pushing..."
  docker build -f "$DOCKERFILE_BASE" -t "$REGISTRY/$IMAGE_NAME:$TAG" .
  docker build -f "$DOCKERFILE_BASE" -t "$REGISTRY/$IMAGE_NAME:latest" .
  docker push "$REGISTRY/$IMAGE_NAME:$TAG"
  docker push "$REGISTRY/$IMAGE_NAME:latest"
fi

# Update the ARG in the app Dockerfile
sed -i "s|ARG BASE_IMAGE=.*|ARG BASE_IMAGE=$REGISTRY/$IMAGE_NAME:$TAG|" "$DOCKERFILE_APP"

echo "Successfully updated $DOCKERFILE_APP to use base image $REGISTRY/$IMAGE_NAME:$TAG"
