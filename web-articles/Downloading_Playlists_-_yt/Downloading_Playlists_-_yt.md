# Downloading Playlists - yt
> 原文链接: https://mintlify.wiki/yt-dlp/yt-dlp/guides/playlists

---

[yt-dlp home page

yt-dlp

](https://mintlify.wiki/yt-dlp/yt-dlp)

Search...

Ctrl K

Search...

Navigation

Guides

Downloading Playlists

[Documentation

](https://mintlify.wiki/yt-dlp/yt-dlp)[CLI Reference

](https://mintlify.wiki/yt-dlp/yt-dlp/cli/general-options)[Python API

](https://mintlify.wiki/yt-dlp/yt-dlp/api/overview)

##### Getting Started

-   [

    Introduction to yt-dlp

    ](https://mintlify.wiki/yt-dlp/yt-dlp)
-   [

    Installation

    ](https://mintlify.wiki/yt-dlp/yt-dlp/installation)
-   [

    Quick start guide

    ](https://mintlify.wiki/yt-dlp/yt-dlp/quickstart)

##### Core Concepts

-   [

    Format Selection

    ](https://mintlify.wiki/yt-dlp/yt-dlp/core-concepts/format-selection)
-   [

    Output Templates

    ](https://mintlify.wiki/yt-dlp/yt-dlp/core-concepts/output-templates)
-   [

    Configuration Files

    ](https://mintlify.wiki/yt-dlp/yt-dlp/core-concepts/configuration)
-   [

    Authentication

    ](https://mintlify.wiki/yt-dlp/yt-dlp/core-concepts/authentication)

##### Guides

-   [

    Downloading Videos

    ](https://mintlify.wiki/yt-dlp/yt-dlp/guides/downloading-videos)
-   [

    Audio Extraction

    ](https://mintlify.wiki/yt-dlp/yt-dlp/guides/audio-extraction)
-   [

    Format Conversion

    ](https://mintlify.wiki/yt-dlp/yt-dlp/guides/format-conversion)
-   [

    Metadata Modification

    ](https://mintlify.wiki/yt-dlp/yt-dlp/guides/metadata-modification)
-   [

    Post-Processing

    ](https://mintlify.wiki/yt-dlp/yt-dlp/guides/post-processing)
-   [

    SponsorBlock Integration

    ](https://mintlify.wiki/yt-dlp/yt-dlp/guides/sponsorblock)
-   [

    Downloading Playlists

    ](https://mintlify.wiki/yt-dlp/yt-dlp/guides/playlists)

##### Advanced

-   [

    Plugin System

    ](https://mintlify.wiki/yt-dlp/yt-dlp/advanced/plugins)
-   [

    Embedding yt-dlp

    ](https://mintlify.wiki/yt-dlp/yt-dlp/advanced/embedding)
-   [

    Creating Custom Extractors

    ](https://mintlify.wiki/yt-dlp/yt-dlp/advanced/custom-extractors)
-   [

    Common Workarounds

    ](https://mintlify.wiki/yt-dlp/yt-dlp/advanced/workarounds)

##### Reference

-   [

    Supported Sites

    ](https://mintlify.wiki/yt-dlp/yt-dlp/reference/supported-sites)
-   [

    Dependencies

    ](https://mintlify.wiki/yt-dlp/yt-dlp/reference/dependencies)
-   [

    Troubleshooting

    ](https://mintlify.wiki/yt-dlp/yt-dlp/reference/troubleshooting)
-   [

    Frequently Asked Questions

    ](https://mintlify.wiki/yt-dlp/yt-dlp/reference/faq)

On this page

-   [Overview](#overview)
-   [Basic Playlist Download](#basic-playlist-download)
-   [YouTube Channels](#youtube-channels)
-   [Selective Download](#selective-download)
-   [Download specific videos from playlist](#download-specific-videos-from-playlist)
-   [Filter by date](#filter-by-date)
-   [Filter by criteria](#filter-by-criteria)
-   [Organizing Playlist Downloads](#organizing-playlist-downloads)
-   [Create folder structure](#create-folder-structure)
-   [Download Archive](#download-archive)
-   [Handling Large Playlists](#handling-large-playlists)
-   [Rate limiting and delays](#rate-limiting-and-delays)
-   [Ignore errors](#ignore-errors)
-   [Limit downloads](#limit-downloads)
-   [Playlist Processing Options](#playlist-processing-options)
-   [Reverse order](#reverse-order)
-   [Random order](#random-order)
-   [Lazy playlist](#lazy-playlist)
-   [Playlist Metadata](#playlist-metadata)
-   [Save playlist info](#save-playlist-info)
-   [Skip playlist metadata](#skip-playlist-metadata)
-   [Common Playlist Scenarios](#common-playlist-scenarios)
-   [Subscribe to a channel](#subscribe-to-a-channel)
-   [Music playlist](#music-playlist)
-   [Educational course](#educational-course)
-   [Podcast archive](#podcast-archive)
-   [Flat Playlist Mode](#flat-playlist-mode)
-   [Concatenating Playlists](#concatenating-playlists)
-   [Batch Downloading Multiple Playlists](#batch-downloading-multiple-playlists)
-   [Performance Optimization](#performance-optimization)
-   [Parallel fragment downloads](#parallel-fragment-downloads)
-   [External downloader](#external-downloader)
-   [Monitoring Progress](#monitoring-progress)
-   [Troubleshooting](#troubleshooting)
-   [Playlist not loading completely](#playlist-not-loading-completely)
-   [Private or deleted videos](#private-or-deleted-videos)
-   [Geo-restricted content](#geo-restricted-content)
-   [Authentication required](#authentication-required)
-   [Next Steps](#next-steps)

> ## Documentation Index
>
> Fetch the complete documentation index at: [https://mintlify.com/yt-dlp/yt-dlp/llms.txt](https://mintlify.com/yt-dlp/yt-dlp/llms.txt)
>
> Use this file to discover all available pages before exploring further.

##

[​

](#overview)

Overview

yt-dlp can download entire playlists, channels, user uploads, and other collections from supported sites. This guide covers best practices for handling playlists efficiently.

##

[​

](#basic-playlist-download)

Basic Playlist Download

Download all videos from a playlist:

```
# Download entire playlist
yt-dlp PLAYLIST_URL

# YouTube playlist example
yt-dlp "https://www.youtube.com/playlist?list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf"
```

By default, yt-dlp downloads all videos in a playlist sequentially.

##

[​

](#youtube-channels)

YouTube Channels

Download from YouTube channels:

All Uploads

Specific Tabs

Community Features

```
# Channel URL downloads all uploads
yt-dlp "https://www.youtube.com/@ChannelName"
yt-dlp "https://www.youtube.com/c/ChannelName"
yt-dlp "https://www.youtube.com/channel/UC..."
```

Accessing private playlists (liked videos, watch later, etc.) requires authentication with `--cookies-from-browser` or `--username/--password`.

##

[​

](#selective-download)

Selective Download

###

[​

](#download-specific-videos-from-playlist)

Download specific videos from playlist

1

[

](#)

By index

```
# Download first 5 videos
yt-dlp -I 1:5 PLAYLIST_URL

# Download videos 3, 5, and 7
yt-dlp -I 3,5,7 PLAYLIST_URL

# Download from 10 to end
yt-dlp -I 10: PLAYLIST_URL
```

2

[

](#)

By range with step

```
# Every other video
yt-dlp -I ::2 PLAYLIST_URL

# Every 3rd video from 1 to 30
yt-dlp -I 1:30:3 PLAYLIST_URL
```

3

[

](#)

Reverse order

```
# Download last 10 videos
yt-dlp -I -10: PLAYLIST_URL

# Download in reverse order
yt-dlp -I ::-1 PLAYLIST_URL
```

###

[​

](#filter-by-date)

Filter by date

```
# Videos from last week
yt-dlp --dateafter today-1week PLAYLIST_URL

# Videos from 2024
yt-dlp --dateafter 20240101 --datebefore 20241231 PLAYLIST_URL

# Videos older than 1 year
yt-dlp --datebefore today-1year PLAYLIST_URL
```

###

[​

](#filter-by-criteria)

Filter by criteria

```
# Videos longer than 10 minutes
yt-dlp --match-filters "duration > 600" PLAYLIST_URL

# Videos with more than 10k views
yt-dlp --match-filters "view_count > 10000" PLAYLIST_URL

# Not live streams
yt-dlp --match-filters "!is_live" PLAYLIST_URL

# Multiple conditions
yt-dlp --match-filters "duration > 600 & view_count > 1000" PLAYLIST_URL
```

##

[​

](#organizing-playlist-downloads)

Organizing Playlist Downloads

###

[​

](#create-folder-structure)

Create folder structure

By Playlist

By Uploader

By Date

Numbered

```
# Each playlist in its own folder
yt-dlp -o "%(playlist)s/%(playlist_index)s - %(title)s.%(ext)s" PLAYLIST_URL
```

##

[​

](#download-archive)

Download Archive

Avoid re-downloading videos you already have:

1

[

](#)

Create download archive

```
# Track downloaded videos
yt-dlp --download-archive archive.txt PLAYLIST_URL
```

2

[

](#)

Update playlist

```
# Only download new videos
yt-dlp --download-archive archive.txt PLAYLIST_URL
```

Videos in `archive.txt` will be skipped.

3

[

](#)

Multiple playlists

```
# Share archive across playlists
yt-dlp --download-archive ~/youtube-archive.txt PLAYLIST_URL_1
yt-dlp --download-archive ~/youtube-archive.txt PLAYLIST_URL_2
```

The download archive is a simple text file containing video IDs. You can manually edit it if needed.

##

[​

](#handling-large-playlists)

Handling Large Playlists

###

[​

](#rate-limiting-and-delays)

Rate limiting and delays

```
# Be respectful to servers
yt-dlp \
  --sleep-interval 5 \
  --max-sleep-interval 15 \
  --sleep-requests 1 \
  PLAYLIST_URL
```

###

[​

](#ignore-errors)

Ignore errors

```
# Continue on errors (deleted/private videos)
yt-dlp --ignore-errors PLAYLIST_URL

# Skip after N errors
yt-dlp --abort-on-error --skip-playlist-after-errors 10 PLAYLIST_URL
```

###

[​

](#limit-downloads)

Limit downloads

```
# Download only first 50 videos
yt-dlp --max-downloads 50 PLAYLIST_URL

# Stop when encountering existing video
yt-dlp --break-on-existing --download-archive archive.txt PLAYLIST_URL
```

##

[​

](#playlist-processing-options)

Playlist Processing Options

###

[​

](#reverse-order)

Reverse order

```
# Download newest first
yt-dlp --playlist-reverse PLAYLIST_URL

# Or using -I
yt-dlp -I ::-1 PLAYLIST_URL
```

###

[​

](#random-order)

Random order

```
# Download in random order
yt-dlp --playlist-random PLAYLIST_URL
```

###

[​

](#lazy-playlist)

Lazy playlist

```
# Process entries as they arrive (for large playlists)
yt-dlp --lazy-playlist PLAYLIST_URL
```

`--lazy-playlist` is useful for very large playlists as it doesn’t wait to load all entries before starting downloads.

##

[​

](#playlist-metadata)

Playlist Metadata

###

[​

](#save-playlist-info)

Save playlist info

```
# Write playlist metadata files
yt-dlp --write-playlist-metafiles PLAYLIST_URL

# This creates:
# - playlist.info.json
# - playlist.description
# - Individual video .info.json files
```

###

[​

](#skip-playlist-metadata)

Skip playlist metadata

```
# Only write video metadata
yt-dlp --no-write-playlist-metafiles PLAYLIST_URL
```

##

[​

](#common-playlist-scenarios)

Common Playlist Scenarios

###

[​

](#subscribe-to-a-channel)

Subscribe to a channel

```
# Daily cron job to download new videos
yt-dlp \
  --download-archive ~/Videos/channel-archive.txt \
  --dateafter today-1week \
  -o "~/Videos/%(uploader)s/%(upload_date)s - %(title)s.%(ext)s" \
  "https://www.youtube.com/@ChannelName/videos"
```

###

[​

](#music-playlist)

Music playlist

```
yt-dlp -x --audio-format mp3 \
  --download-archive music-archive.txt \
  --embed-metadata \
  --embed-thumbnail \
  --parse-metadata "%(playlist_title|)s:%(meta_album)s" \
  --parse-metadata "%(uploader|)s:%(meta_artist)s" \
  --parse-metadata "%(playlist_index|)s:%(meta_track)s" \
  -o "%(artist,uploader)s/%(album,playlist)s/%(track)s - %(title)s.%(ext)s" \
  PLAYLIST_URL
```

###

[​

](#educational-course)

Educational course

```
yt-dlp \
  -o "%(playlist)s/%(chapter_number|)s%(playlist_index)s - %(title)s.%(ext)s" \
  --write-subs \
  --embed-subs \
  --embed-metadata \
  PLAYLIST_URL
```

###

[​

](#podcast-archive)

Podcast archive

```
yt-dlp -x --audio-format mp3 \
  --download-archive podcast-archive.txt \
  --embed-metadata \
  --embed-thumbnail \
  -o "Podcasts/%(uploader)s/%(upload_date)s - %(title)s.%(ext)s" \
  CHANNEL_URL
```

##

[​

](#flat-playlist-mode)

Flat Playlist Mode

Extract playlist information without downloading:

```
# List all video URLs without downloading
yt-dlp --flat-playlist --print url PLAYLIST_URL

# Get video IDs
yt-dlp --flat-playlist --print id PLAYLIST_URL

# Get full metadata without downloading
yt-dlp --flat-playlist --dump-json PLAYLIST_URL
```

Use `--flat-playlist` to quickly check playlist contents or create custom processing workflows.

##

[​

](#concatenating-playlists)

Concatenating Playlists

Merge playlist videos into single file:

```
# Concatenate multi-part videos (default)
yt-dlp --concat-playlist multi_video PLAYLIST_URL

# Always concatenate all videos
yt-dlp --concat-playlist always \
  -o "pl_video:%(playlist)s.%(ext)s" \
  PLAYLIST_URL

# Never concatenate
yt-dlp --concat-playlist never PLAYLIST_URL
```

All videos must have the same codecs and number of streams to be concatenated.

##

[​

](#batch-downloading-multiple-playlists)

Batch Downloading Multiple Playlists

Create a file with multiple playlist URLs:

playlists.txt

```
# Music playlists
https://www.youtube.com/playlist?list=PLxxxxxxx
https://www.youtube.com/playlist?list=PLyyyyyyy

# Educational
https://www.youtube.com/playlist?list=PLzzzzzzz
```

Download all:

```
yt-dlp -a playlists.txt \
  --download-archive archive.txt \
  -o "%(playlist)s/%(title)s.%(ext)s"
```

##

[​

](#performance-optimization)

Performance Optimization

###

[​

](#parallel-fragment-downloads)

Parallel fragment downloads

```
# Download fragments in parallel (faster for HLS/DASH)
yt-dlp -N 4 PLAYLIST_URL
```

###

[​

](#external-downloader)

External downloader

```
# Use aria2c for faster downloads
yt-dlp --downloader aria2c \
  --downloader-args "aria2c:-x 16 -s 16 -k 1M" \
  PLAYLIST_URL
```

##

[​

](#monitoring-progress)

Monitoring Progress

Track download progress:

```
# Show progress bar
yt-dlp --progress PLAYLIST_URL

# Console title (terminal window title)
yt-dlp --console-title PLAYLIST_URL

# Custom progress template
yt-dlp --progress-template "download:%(info.title)s %(progress.percent)s" PLAYLIST_URL
```

##

[​

](#troubleshooting)

Troubleshooting

###

[​

](#playlist-not-loading-completely)

Playlist not loading completely

```
# Use lazy playlist for large playlists
yt-dlp --lazy-playlist PLAYLIST_URL

# Increase timeout
yt-dlp --socket-timeout 30 PLAYLIST_URL
```

###

[​

](#private-or-deleted-videos)

Private or deleted videos

```
# Skip unavailable videos
yt-dlp --ignore-errors PLAYLIST_URL

# See which videos are unavailable (YouTube)
yt-dlp --flat-playlist --print "%(title)s [%(id)s] %(availability)s" PLAYLIST_URL
```

###

[​

](#geo-restricted-content)

Geo-restricted content

```
# Use proxy for restricted videos
yt-dlp --proxy socks5://127.0.0.1:1080 PLAYLIST_URL

# Fake location
yt-dlp --xff "US" PLAYLIST_URL
```

###

[​

](#authentication-required)

Authentication required

```
# Use browser cookies
yt-dlp --cookies-from-browser firefox PLAYLIST_URL

# Or login credentials
yt-dlp --username USERNAME --password PASSWORD PLAYLIST_URL
```

##

[​

](#next-steps)

Next Steps

[

## Downloading Videos

Basic video download workflows

](https://mintlify.wiki/yt-dlp/yt-dlp/guides/downloading-videos)

[

## Audio Extraction

Extract audio from playlist videos

](https://mintlify.wiki/yt-dlp/yt-dlp/guides/audio-extraction)

[

## Post-Processing

Process downloaded videos

](https://mintlify.wiki/yt-dlp/yt-dlp/guides/post-processing)

[

## Output Templates

Customize file naming and organization

](https://mintlify.wiki/yt-dlp/yt-dlp/core-concepts/output-templates)

[

SponsorBlock Integration

Previous

](https://mintlify.wiki/yt-dlp/yt-dlp/guides/sponsorblock)[

Plugin System

Next

](https://mintlify.wiki/yt-dlp/yt-dlp/advanced/plugins)

Ctrl+I

Rate your experience

How was the docs repo generation?

12345

PoorExcellent

## Build docs developers (and LLMs) love

[Get started for free](https://dashboard.mintlify.com/signup?utm_campaign=atlas_referral&utm_medium=yt-dlp-yt-dlp&utm_source=atlas_signup)[Talk to us](https://www.mintlify.com/contact/sales?utm_campaign=atlas_referral&utm_medium=yt-dlp-yt-dlp&utm_source=atlas_sales)