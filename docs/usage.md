# Usage

The `updatr` command synchronizes a set of photos with Flickr.

The photos must already reside on Flickr. It is easy to bulk upload new photos to Flickr
by using the "Upload Photos" button on its webinterface.

But if you subsequently change the metadata of those photos, it gets a bit tricky to reflect
those changes on Flickr without deleting and re-importing the photo.
(We do not want to delete photos because of the comments that may have been added).

# Input

Give your set of photos a name, and make a directory with that name under the `BASE` directory.
The `BASE` is hard coded as your Dropbox folder.
We refer to the name of this directory as the *folderName*.

Inside this folder,

*   make a subfolder `photos` and put your photos in (`jpg` format).
*   make a subfolder `metadata`and put your metadata in (`yaml` format).
    See below for the available metadata fields.

Upload the content of `photos` to Flickr and put them in an album, and give that album any name you like.
Remember that name. We refer to it as the *albumName*.

Next to the subfolders `photos` and `metadata`, make a file `config.yaml` with contents analogous to the one found 
[here](https://www.dropbox.com/sh/ofbei5tfewu40k5/AACTIT2CwW7MkwuWxYq3r2a5a?dl=0)

``` yaml=
albumName: TestSet
colofon: "Foto: {author}; bewerker: {writer}\n{copyright}"
metaDefaults:
  source: "test"
  credit: "https://github.com/dirkroorda/photo-workflow/blob/master/test/metadata"
  author: "onbekend"
  writer: "Dirk Roorda"
  copyright: "© zie {credit}/{sourceAsUrl}.txt"
  caption: "test photo"
  keywords:
    - my
    - now
```

Line by line:

1.  the *albumName* on Flickr. We only work with photos that are in this album.
1.  *colofon*: a template to add standard material at the end of the caption, such as a copyright notice.
1.  *metaDefaults*: a list of metadata fields and their default values:
1.  *source*: something that identifies the source photo (e.g. an instance of it in a public repository) 
1.  *credit*: a public repository that holds the photo, preferably in the form of a url
1.  *author*: maker or publisher of the original photo
1.  *writer*: editor/compiler of the metadata of the photo
1.  *copyright*: a template for mentioning a copyright notice.
1.  You can use this to generate a direct link to the original in the public repository.
1.  *caption*: description of the photo.
1.  *keywords*: a list of keywords for the photo.
    The default acts as a list of keywords that is applied to all photos in the set.

# Scenario

The following scenarios are supported:

## Change metadata and sync changes to Flickr

You can change the `yaml` files at will and then run

```sh
updatr folderName flickr
```

This will perform the following steps:

1.  merge the changed `yaml` files into the `jpg` files
2. on Flickr, replace the corresponding images by the updated `jpg` files.
   Flickr *replace* performs a reupload of the image file and it will harvest the new Exif information.
   By itself, it will not update the captions and it will not sync the keyword based albums if keywords have been changed.
   So we use the [Flickr API](https://www.flickr.com/services/api/) to update the captions.
   We use it as will to update the albums, and after that, to re-sort them.

## Change metadata and merge them into image files

You can change the `yaml` files at will an then run

```sh
updatr folderName importmeta
```

or

```sh
updatr folderName importmeta force
```

This will merge the metadata of the `yaml`files into the `jpg` files.
In the case with `force`, all `yaml` files will be merged, in the case without `force`,
only changed `yaml` files will be merged.

## Export metadata from image files

You can export the metadata from the image files.

```sh
updatr folderName exportmeta
```

or

```sh
updatr folderName exportmeta full
```

This creates a new directory `metadata` under `_local/folderName` in this repository.
(Note that `_local` is in the `.gitignore` file and will not be added to the git repo, and hence will
not be pushed to GitHub.

The metadata will be read off from the `jpg` files.
Whenever the value coincides with the default value, it will be left out.

Unless you have passed `full`, in that case the metadata will be exported as is.

## Change locations directly in the image files

You can use any software to add GPS locations to your `jpg` images.
After doing so, their modification times have changed, and you can synchronize them to Flickr by

``` sh
updatr folderName flickr
```

## Sort albums on Flickr

If something has gone wrong with the synchronzation of Flickr,
you might end up with albums whose photos are no longer chronologically sorted.
That can be remedied by

``` sh
updatr folderName sortalbums
```
