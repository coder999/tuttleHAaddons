# Home Assistant Add-ons

This repository contains custom Home Assistant add-ons created by Mark Tuttle.

These add-ons are intended for users who want to install third-party Home Assistant add-ons from a public GitHub repository.

## Add-ons

- [Markdown Wiki](markdown-wiki/README.md) - Simple Markdown file viewer with sidebar navigation

## Installing This Repository in Home Assistant

Home Assistant supports adding third-party app repositories directly from a Git repository URL.

Summary of the official process:

1. Copy the HTTPS URL of this GitHub repository.
2. In Home Assistant, go to **Settings > Apps > App Store**.
3. Open the menu in the top-right corner and select **Repositories**.
4. Paste the repository URL and select **Add**.
5. Home Assistant will add this repository and list the available add-ons.

Official Home Assistant documentation:

- [Installing a third-party app repository](https://www.home-assistant.io/common-tasks/os#installing-a-third-party-app-repository)

## Notes

- Home Assistant warns that third-party add-ons are used at your own risk.
- If the repository does not appear after adding it, refresh the browser and check the Supervisor logs for repository validation errors.
- Each add-on in this repository has its own README with installation and usage details.