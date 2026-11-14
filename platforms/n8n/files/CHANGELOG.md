# Changelog

## 0.1.3

- GPT Image models follow the aspect ratio: with Size empty, they get the nearest size (square, 1536x1024 or 1024x1536).
- The image model list leaves out gemini-2.5-flash-image, gpt-image-1 and gpt-image-1.5.
- The credential and README say that new accounts get free trial credit.

## 0.1.2

- The package now lives in its own repository, github.com/steadyrouter/n8n-nodes-steadyrouter, and is published from there.
- The chat model node's codex file keeps only the documented fields.
- Generated images can be up to 200 MB (was 50 MB), so large 4K images are not refused.

## 0.1.1

- Publish from the package source committed in the repository, so the n8n package scan can read it. No functional change.

## 0.1.0

- First release: SteadyRouter node (Text, Image, Video) and SteadyRouter Chat Model for AI Agent.
