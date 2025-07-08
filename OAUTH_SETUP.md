# SmartThings OAuth Setup Guide

This integration now uses OAuth2 instead of Personal Access Tokens for better security and compliance with Samsung SmartThings requirements.

## Prerequisites

1. Home Assistant with external access (HTTPS required for OAuth)
2. A Samsung SmartThings Developer Account

## Setup Steps

### 1. Create a SmartThings Application

1. Go to https://smartthings.developer.samsung.com/
2. Sign in with your Samsung account
3. Click "Create new project" and select "Device integration" or "SmartApp"
4. Fill in your project details:
   - **Project Name**: Home Assistant Integration
   - **Organization**: Your organization name
   - **Project Type**: Device integration

### 2. Configure OAuth

1. In your SmartThings project, go to the "OAuth" section
2. Set up the OAuth client:
   - **Client Display Name**: Home Assistant
   - **Authorization Redirect URIs**: `https://your-home-assistant-url/auth/external/callback`
   - **Scope**: Select the required scopes:
     - `r:devices:*` (read devices)
     - `w:devices:*` (write devices) 
     - `x:devices:*` (execute device commands)
     - `r:hubs:*` (read hubs)
     - `r:locations:*` (read locations)
     - `w:locations:*` (write locations)
     - `x:locations:*` (execute location commands)
     - `r:scenes:*` (read scenes)
     - `x:scenes:*` (execute scenes)
     - `r:rules:*` (read rules)
     - `w:rules:*` (write rules)
     - `sse` (server-sent events)
     - `r:installedapps` (read installed apps)
     - `w:installedapps` (write installed apps)

3. Save your OAuth configuration and note down:
   - **Client ID**
   - **Client Secret**

### 3. Configure Home Assistant

1. Go to **Settings** > **Devices & Services**

2. Click **Add Integration** and search for "SmartThings"

3. You'll be prompted to enter your SmartThings OAuth credentials:
   - **Client ID**: Enter your SmartThings OAuth Client ID
   - **Client Secret**: Enter your SmartThings OAuth Client Secret

4. Click **Submit** and follow the OAuth flow to authorize Home Assistant with SmartThings

5. Complete the authorization in your browser when redirected to SmartThings

## Migration from Personal Access Token

If you previously used this integration with Personal Access Tokens:

1. Remove the old SmartThings integration entry
2. Follow the OAuth setup above
3. Re-add the SmartThings integration using OAuth

Your devices and entities will be re-discovered automatically.

## Troubleshooting

### Invalid Redirect URI
- Ensure your Home Assistant URL is accessible externally
- Check that the redirect URI in SmartThings matches exactly: `https://your-home-assistant-url/auth/external/callback`

### Missing Scopes
- Verify all required scopes are selected in your SmartThings OAuth configuration
- The integration will fail if any required scopes are missing

### SSL Certificate Issues
- Home Assistant must be accessible via HTTPS for OAuth to work
- Consider using Let's Encrypt or a reverse proxy with valid SSL certificates

## Benefits of OAuth vs Personal Access Tokens

- **Better Security**: OAuth tokens are automatically refreshed and have limited scope
- **Compliance**: Meets Samsung's requirements for production integrations
- **User Experience**: No need to manually generate and manage tokens
- **Granular Permissions**: Only request the specific permissions needed
