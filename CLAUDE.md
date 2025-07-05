# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TgPosteer is an advanced automated Telegram bot system that fetches, processes, and posts anime content to Telegram channels. It uses a sophisticated microservices architecture with AI-powered content enhancement through Stable Diffusion WebUI and LM Studio, featuring intelligent content quality control and comprehensive monitoring.

## Development Commands

### Running the Application
```bash
# Main bot orchestrator (primary system)
python orchestrator.py

# Django dashboard (monitoring and control)
cd dashboard && python manage.py runserver

# View real-time logs
tail -f logs/tgposter.log

# Legacy system (deprecated but maintained)
python main2.py
```

### Django Dashboard Commands
```bash
cd dashboard
python manage.py migrate
python manage.py collectstatic
python manage.py runserver 0.0.0.0:8000
```

### Development Tools
```bash
# Check syntax
python3 -m py_compile orchestrator.py
python3 -m py_compile services/*.py

# View database
sqlite3 telegram_bot.db
```

## Architecture Overview

### Enhanced Microservices Structure (`/services/`)
- **`db_service.py`** - SQLite database operations with async support and schema auto-migration
- **`reddit_service.py`** - Advanced Reddit content fetching with gallery support and media type detection
- **`telegram_service.py`** - Telegram Bot API integration with smart compression and media group support
- **`sd_service.py`** - Stable Diffusion WebUI image analysis with multi-model fallback and tagger extension
- **`lm_service.py`** - LM Studio text generation with negative example learning and advanced prompt engineering
- **`waifu_service.py`** - Waifu.fm API integration as fallback content source

### Core Components
- **`orchestrator.py`** - Advanced coordination service with multi-step processing pipeline and intelligent fallbacks
- **`dashboard/`** - Django web interface with real-time analytics, content quality control, and interactive management
- **`vars.yaml`** - Centralized configuration for SQL queries, AI prompts, content rules, and system settings
- **`main2.py`** - Legacy implementation (deprecated but maintained for compatibility)

### Advanced Content Processing Pipeline
1. **Multi-Source Strategy**: Sequential processing of Reddit sources with intelligent failover
2. **Content Type Detection**: Images, videos, GIFs, and galleries with appropriate handling
3. **AI Enhancement Pipeline**: 
   - Image analysis through SD WebUI (DeepDanbooru → Clip → Interrogate cascade)
   - Advanced tag filtering (150+ excluded patterns)
   - First-person narrative generation via LM Studio
4. **Quality Control**: Post marking system with negative example learning
5. **Smart Publishing**: Telegram optimization with compression and formatting

## Database Schema

### Main Tables
- **`post_logs`** - Complete posting history with AI metadata and quality control
- **`reddit_posts`** - Duplicate prevention tracking with post IDs and processing timestamps

### Enhanced Schema Fields
- **AI Integration**: `interrogate_model`, `description_model`, `interrogate_method`, `interrogate_prompt`
- **Content Metadata**: `tags`, `description`, `image_data`, `image_url`
- **Quality Control**: `marked` (0/1), `tagged` (content flags)
- **Processing Tracking**: `published_at`, `created_at` timestamps

### Tag Storage System
- **Format**: Pipe-separated values (`tag1|tag2|tag3`) for reliable parsing
- **Compatibility**: Dashboard handles both old (comma) and new (pipe) formats
- **Processing**: Advanced cleaning removes unwanted symbols (`#`, `:`, emojis) from beginnings

## Configuration Management

### Environment Variables (`.env`)
- **Core Settings**:
  - `BOT_TOKEN` - Telegram bot authentication
  - `CHANNEL_ID` - Target posting channel
  - `DATABASE_PATH` - SQLite database location
- **AI Services**:
  - `SD_URL` - Stable Diffusion WebUI endpoint
  - `LM_STUDIO_URL` - Language model API endpoint
- **Reddit Integration**:
  - Reddit API credentials and user agent

### YAML Configuration (`vars.yaml`)
- **Content Sources**: Array-based subreddit configuration with priorities
- **AI Prompts**: Advanced prompt engineering with РАЗРЕШЕНИЯ/ЗАПРЕТЫ sections
- **Content Filtering**: Comprehensive tag exclusion lists (150+ patterns)
- **SQL Templates**: Statistical and operational database queries
- **Service Settings**: Timing, timeouts, and processing configurations

## Key Architectural Patterns

### Async/Await Throughout
All services implement full async patterns for optimal performance with external API calls and database operations.

### Intelligent Fallback Systems
- **Content Sources**: Reddit primary → Reddit secondary → Waifu.fm → Individual processing
- **AI Models**: DeepDanbooru → DeepBooru → CLIP → Interrogate cascade
- **Error Recovery**: Graceful degradation with detailed logging

### Advanced Content Quality Control
- **Tag Processing Pipeline**:
  1. AI response parsing (handles comma and space-separated formats)
  2. Symbol cleaning (removes `#`, `:`, emojis from beginnings)
  3. Content filtering (excludes 150+ inappropriate/generic tags)
  4. Hashtag generation (clean tags formatted as `#tag1 #tag2`)
- **Negative Example Learning**: Marked posts influence future content generation
- **Content Type Optimization**: Different processing for images, videos, GIFs, galleries

### Smart Media Handling
- **Automatic Compression**: Images optimized for Telegram (50MB limit with quality scaling)
- **Dimension Validation**: Ensures compatibility with Telegram size restrictions
- **Format Optimization**: JPEG conversion for optimal compression ratios

## AI Integration Points

### Stable Diffusion WebUI
- **Multi-Model Interrogation**: Cascading through DeepDanbooru, DeepBooru, CLIP, and Interrogate
- **Tagger Extension Support**: Advanced tagging with confidence thresholds (0.35)
- **Intelligent Response Parsing**: Handles both comma and space-separated tag formats
- **Model Availability Detection**: Automatic fallback when specific models unavailable

### LM Studio
- **Advanced Prompt Engineering**: First-person narrative focus with explicit content guidelines
- **Negative Example Integration**: Learns from marked posts to avoid unwanted patterns
- **Smart Text Processing**: Intelligent truncation at sentence boundaries (150-250 chars)
- **Temperature Optimization**: Increased to 0.9 for diverse content generation

## Monitoring and Analytics

### Django Dashboard Features
- **Real-time Statistics**: 6-card overview showing posts/day, totals, success rates, DB metrics
- **Interactive Content Management**: AJAX-powered post marking without page reloads
- **Advanced Analytics**:
  - 7-day activity charts (Chart.js integration)
  - AI model performance tracking with failure rates
  - Tag analytics with length and frequency metrics
- **Quality Control Interface**: Visual indicators for successful/failed posts

### Enhanced Logging System
- **Colored Console Output**: Emoji-enhanced logs with severity-based coloring
- **File Rotation**: Automatic rotation at 10MB with 5 backup files
- **Structured Logging**: DEBUG/INFO/WARNING/ERROR levels with contextual information
- **Performance Tracking**: Execution time measurement for processing cycles

### Database Health Monitoring
- **Size Tracking**: Database growth monitoring with size metrics
- **Schema Validation**: Automatic detection and creation of missing columns
- **Performance Metrics**: Query execution time and optimization tracking

## Development Guidelines

### Adding New Services
1. Create service file in `/services/` directory following async patterns
2. Implement error handling with graceful degradation
3. Add configuration to `vars.yaml` if needed
4. Update `orchestrator.py` integration with fallback mechanisms
5. Add monitoring and logging throughout

### Database Schema Changes
- Use `db_service.py` for all database operations
- Implement automatic schema migration for new columns
- Maintain backward compatibility with existing data
- Update analytics queries in `vars.yaml`

### AI Service Integration Best Practices
- Follow established patterns in `sd_service.py` and `lm_service.py`
- Implement multi-model fallback mechanisms
- Add comprehensive error handling and timeout management
- Configure prompts in `vars.yaml` for maintainability
- Include negative example learning where applicable

### Tag Processing Guidelines
- Always use `filter_tags()` function for consistent tag cleaning
- Store tags with pipe separator (`|`) in database
- Handle both comma and space-separated AI responses
- Remove special characters (`#`, `:`, emojis) from tag beginnings
- Limit display hashtags to 10 per post for Telegram compatibility

### Content Quality Control
- Implement post marking capabilities for quality feedback
- Use marked posts as negative examples for AI training
- Monitor success/failure rates through dashboard analytics
- Maintain content guidelines in `vars.yaml` ЗАПРЕТЫ section

### Performance Optimization
- Use async/await patterns throughout
- Implement proper connection pooling for HTTP clients
- Clean up image data and file handles appropriately
- Monitor memory usage and implement garbage collection where needed

## Legacy Code Management

### Backward Compatibility
- **`main2.py`**: Legacy implementation preserved for reference
- **Database Format**: Dashboard handles both old and new tag storage formats
- **Configuration Migration**: Smooth transition support for environment variables

### Migration Path
- Primary development should focus on `orchestrator.py`
- New features should be implemented in the modern architecture
- Legacy code maintenance should be minimal and focused on compatibility