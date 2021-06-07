import os
import yaml

import osxphotos


keywordsFromName = {}

SOURCE = "EenEeuwEefde"
BASE = os.path.expanduser(f"~/DropboxTest/{SOURCE}")
PHLIB = os.path.expanduser("~/Pictures/EEE.photoslibrary")
PHSET = "Een Eeuw Eefde"
ADDKW = {"Eefde", "historisch"}


def readYaml(path):
    with open(path) as fh:
        settings = yaml.load(fh, Loader=yaml.FullLoader)
    return settings


def phGetMeta():
    photosdb = osxphotos.PhotosDB(
        dbfile=os.path.expanduser(PHLIB)
    )
    photos = photosdb.photos(albums=[PHSET])

    for photoInfo in photos:
        name = photoInfo.original_filename.removesuffix(".jpg")
        keywords = photoInfo.keywords
        useKeywords = []
        for keyword in keywords:
            if keyword not in ADDKW:
                useKeywords.append(keyword)
        keywordsFromName[name] = sorted(useKeywords)


def phPutMeta():
    for (name, kws) in sorted(keywordsFromName.items()):
        metaPath = f"{BASE}/metadata/{name}.yaml"
        meta = readYaml(metaPath)
        meta["keywords"] = kws
        with open(metaPath, "w") as exh:
            yaml.dump(meta, exh, allow_unicode=True)


phGetMeta()
phPutMeta()
