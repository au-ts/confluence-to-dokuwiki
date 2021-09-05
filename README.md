# confluence-to-dokuwiki
A python script to convert a confluence export (and its attachments) to a structure that works with DokuWiki

To use:  extract the Confluence export ZIP file; unzip it.

Edit the Mappings file to add Confluence user-id to your new user-ids in the dictonary there.

Copy the mappings and extract.py files to the root of the unzipped Confluence export

Run
  ```
python3 ./.extract.py
```

This will create a tree of pages and of media, assuming `:oldwiki:` is the top namespace for DokuWiki.
To import, just copy the directory `pages/current` to dokuwiki's `data/pages/oldwiki`; and the `media/oldwiki` to `data/media/oldwiki`
