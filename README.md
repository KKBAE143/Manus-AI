---
title: Manuscript & Quiz Cleaner
emoji: 📚
colorFrom: green
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
short_description: Clean exam PDFs, attach answer keys, build a library
---

# Manuscript & Quiz Cleaner

Upload an NTA / TCS iON exam paper PDF and (optionally) the official answer
key. The app strips platform metadata, removes the Hindi translation
duplicate of every question, attaches the correct answer to each question,
and stores the cleaned PDF in a library you can bulk-download as a ZIP.

For local development docs see [README.dev.md](./README.dev.md).

## Privacy

This Space is **private**: only the listed collaborators can open the URL
or use the app. Uploaded PDFs and generated outputs are kept in a private
Hugging Face dataset that only you control.

## Maintenance

The Space rebuilds automatically when this repository receives a new commit.
After 48 hours of inactivity the Space sleeps; the next visit wakes it in
~10 seconds and the library is restored from the private dataset.
