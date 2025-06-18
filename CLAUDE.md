# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TgPosteer is an automated Telegram bot system that fetches, processes, and posts anime content to Telegram channels. It uses a microservices architecture with AI-powered content enhancement through Stable Diffusion and language models.

## Development Commands

### Running the Application
```bash
# Main bot orchestrator
python orchestrator.py

# Django dashboard
cd dashboard && python manage.py runserver

# View real-time logs
tail -f logs/tgposter.log
```

### Django Dashboard Commands
```bash
cd dashboard
python manage.py migrate
python manage.py collectstatic
python manage.py runserver 0.0.0.0:8000
```

## Architecture Overview

### Microservices Structure (`/services/`)
- **`db_service.py`** - SQLite database operations with async support
- **`reddit_service.py`** - Reddit content fetching and media download
- **`telegram_service.py`** - Telegram Bot API integration
- **`sd_service.py`** - Stable Diffusion WebUI image analysis
- **`lm_service.py`** - LM Studio text generation
- **`waifu_service.py`** - Waifu.fm API integration

### Core Components
- **`orchestrator.py`** - Main coordination service that manages all workflows
- **`dashboard/`** - Django web interface for monitoring and analytics
- **`vars.yaml`** - Central configuration for SQL queries, AI prompts, and settings

### Content Processing Pipeline
1. **Source Priority**: Reddit (primary/secondary) → Waifu.fm (fallback)
2. **Media Processing**: Images, videos, GIFs, and galleries
3. **AI Enhancement**: SD for tagging, LM for descriptions
4. **Publishing**: Telegram channel posting with smart formatting

## Database Schema

### Main Tables
- **`post_logs`** - Complete posting history with AI metadata
- **`reddit_posts`** - Duplicate prevention tracking

### Key Fields
- AI model tracking (`interrogate_model`, `description_model`)
- Content metadata (`tags`, `description`, `image_data`)
- Processing timestamps and status flags

## Configuration Management

### Environment Variables (`.env`)
- `BOT_TOKEN` - Telegram bot authentication
- `CHANNEL_ID` - Target posting channel
- `SD_URL` - Stable Diffusion WebUI endpoint
- `LM_STUDIO_URL` - Language model API
- `DATABASE_PATH` - SQLite database location

### YAML Configuration (`vars.yaml`)
- SQL query templates
- AI system prompts and parameters
- Content filtering rules (150+ excluded tags)
- Service timing configurations

## Key Architectural Patterns

### Async/Await Throughout
All services use async patterns for concurrent operations and external API calls.

### Service Isolation
Each service handles a specific domain (Reddit, Telegram, AI) with clear interfaces.

### Fallback Mechanisms
Multiple content sources with automatic failover when primary sources are unavailable.

### Smart Content Filtering
Advanced tag-based filtering system to ensure content quality and appropriateness.

## AI Integration Points

### Stable Diffusion WebUI
- Image interrogation using DeepDanbooru/CLIP
- Tagger extension support
- Confidence-based tag filtering

### LM Studio
- Context-aware description generation
- Configurable temperature and token limits
- Custom system prompts for different content types

## Monitoring and Logging

### Django Dashboard
- Real-time statistics and 7-day activity trends
- Database size and health monitoring
- Processing history and error tracking

### Logging System
- Colored console output with emoji support
- File rotation (10MB limit, 5 backups)
- Structured levels (DEBUG, INFO, WARNING, ERROR)

## Development Guidelines

### Adding New Services
1. Create service file in `/services/` directory
2. Follow async patterns established in existing services
3. Add configuration to `vars.yaml` if needed
4. Update `orchestrator.py` to integrate new service

### Database Changes
- Use `db_service.py` for all database operations
- Maintain async patterns for database calls
- Update schema documentation when adding tables

### AI Service Integration
- Follow patterns in `sd_service.py` and `lm_service.py`
- Add model fallbacks and error handling
- Configure prompts in `vars.yaml` for maintainability