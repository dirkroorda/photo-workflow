import re
import os
import sys
import urllib
from datetime import datetime
from time import sleep
import yaml

import webbrowser
import pprint

import pyexiv2
import flickrapi


pp = pprint.PrettyPrinter(indent=2)


COMMANDS = dict(
    importmeta="""
    apply metadata to photos,
    only if metadata has changed or `force` is passed.
""",
    exportmeta="""
    export defined metadata from photos,
    if `full` is passed, also export default/computed values.
""",
    flickr="""
    sync updates to Flickr, including metadata and album membership;
    if force, sync all photos".
""",
    sortalbums="""
    sort exisiting albums on flickr.
    You can pass a comma-separated list of albums to sort.
""",
    updatealbums="""
    update albums exisiting albums on flickr.
    You can pass a comma-separated list of albums to update.
""",
)
COMMAND_STR = "\n".join(f"{k:<10} : {v}" for (k, v) in sorted(COMMANDS.items()))

IMAGE_BASE = os.path.expanduser("~/Dropbox")
# IMAGE_BASE = os.path.expanduser("~/DropboxTest")

HELP = f"""
updatr source[:name] [command] [flag]

source: a directory name with a photo collection, residing under {IMAGE_BASE}
name  : the name of a photo in the source directory.
        If present, work only with this photo.
        In that case, the force flag will be set and the datestamp
        of the flickr update will be ignored and not updated.

command flag:
{COMMAND_STR}

If no command is given, `flickr` is assumed.

-h
--help
help  : print help and exit
"""


REPO_DIR = f"{os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}"
LOCAL_DIR = f"{REPO_DIR}/_local"
FLICKR_CONFIG = f"{LOCAL_DIR}//flickr.yaml"
FLICKR_UPDATED = f"{LOCAL_DIR}//flickrupdated.txt"


METADATA = (
    ("source", "Iptc.Application2.Source", None),
    ("credit", "Iptc.Application2.Credit", None),
    ("copyright", "Iptc.Application2.Copyright", "Exif.Image.Copyright"),
    ("author", "Iptc.Application2.Byline", "Exif.Image.Artist"),
    ("writer", "Iptc.Application2.Writer", None),
    ("caption", "Iptc.Application2.Caption", "Exif.Image.ImageDescription"),
    ("keywords", "Iptc.Application2.Keywords", None),
    ("datetime", None, "Exif.Image.DateTime"),
)

CAPTION_SEP = "\n---\n"
COLOFON_RE = re.compile(
    r"""(?:(?:\s*\(Bron:\s*)|(?:{})).*$""".format(CAPTION_SEP), re.S
)

CACHE = False


def console(*args, error=False):
    device = sys.stderr if error else sys.stdout
    device.write(" ".join(args) + "\n")
    device.flush()


def pretty(data):
    print(pp.pprint(data))


def sanitize(metadata):
    if "source" in metadata:
        val = metadata["source"]
        if type(val) is not str:
            metadata["source"] = str(val)


def readArgs():
    class A:
        pass

    A.source = None
    A.command = None

    args = sys.argv[1:]

    if not len(args):
        console(HELP)
        console("Missing source and command")
        return None

    if args[0] in {"-h", "--help", "help"}:
        console(HELP)
        return None

    source = args[0]
    parts = source.split(":", 1)
    source = parts[0]
    name = None if len(parts) == 1 else parts[1]

    A.source = source
    A.name = name
    args = args[1:]

    if not len(args):
        A.command = "flickr"
        A.flag = None
        return A

    if args[0] in {"-h", "--help", "help"}:
        console(HELP)
        return None

    command = args[0]
    A.command = command
    args = args[1:]
    flag = None

    if args:
        flag = args[0]
        if (
            flag == "full" and command != "exportmeta"
            or flag == "force" and command not in {"importmeta", "flickr"}
            or flag not in {"full", "force"}
        ):
            console(HELP)
            console(f"Unknown flag `{flag}` for command `{command}`")
            return None

    A.flag = flag

    if command not in COMMANDS:
        console(HELP)
        console(f"Wrong command: «{' '.join(args)}»")
        return None

    return A


def readYaml(path):
    with open(path) as fh:
        settings = yaml.load(fh, Loader=yaml.FullLoader)
    return settings


def getPhotoMeta(inPath, defaults, expanded):
    info = pyexiv2.ImageMetadata(inPath)
    info.read()
    metadata = {}
    eNames = set(info.exif_keys)
    iNames = set(info.iptc_keys)

    actual = {}

    for (log, iName, eName) in METADATA:
        if log == "datetime":
            eNameOrig = f"{eName}Original"
            val = "" if eNameOrig not in eNames else info[eNameOrig].raw_value
            if not val:
                val = "" if eName not in eNames else info[eName].raw_value
        elif log == "keywords":
            val = [""] if iName not in iNames else info[iName].raw_value
        else:
            iVal = [""] if iName not in iNames else info[iName].value
            iVal = "\n".join(iVal)
            eVal = "" if eName not in eNames else info[eName].value
            val = eVal if not iVal or eVal and len(eVal) > len(iVal) else iVal
            if not expanded and log == "caption":
                val = COLOFON_RE.sub("", val)
        actual[log] = val

    actual["sourceAsUrl"] = urllib.parse.quote_plus(actual["source"])

    for (log, iName, eName) in METADATA:
        val = actual[log]

        default = defaults.get(log, None)
        if log == "copyright":
            default = defaults[log].format(**actual)

        if log == "keywords":
            if expanded:
                metadata[log] = sorted(val)
            else:
                val = set(val) - set(defaults[log])
                if val:
                    metadata[log] = sorted(val)
        else:
            if val and (expanded or val != default):
                metadata[log] = val
    return metadata


class Make:
    def __init__(self, source, name):
        class C:
            pass

        self.C = C
        self.source = source
        self.name = name

        if not self.config():
            quit()

    def config(self):
        C = self.C
        source = self.source
        name = self.name

        c = dict(source=source)

        configPath = f"{IMAGE_BASE}/{source}/config.yaml"
        c["photosDir"] = f"{IMAGE_BASE}/{source}/photos"
        c["photoName"] = name
        c["metaDir"] = f"{IMAGE_BASE}/{source}/metadata"

        if not os.path.exists(configPath):
            console(f"No yaml file found: {configPath}")
            return None

        settings = readYaml(configPath)
        for (k, v) in settings.items():
            c[k] = v

        c["metaOutDir"] = f"{LOCAL_DIR}/{source}/metadata"
        c["metaxOutDir"] = f"{LOCAL_DIR}/{source}/metadatax"

        if not os.path.exists(FLICKR_CONFIG):
            console(f"No flickr config file found: {FLICKR_CONFIG}")
            return None

        flickrSettings = readYaml(FLICKR_CONFIG)
        for (k, v) in flickrSettings.items():
            c[k] = v

        for (k, v) in c.items():
            setattr(C, k, v)

        if not self.collectPhotos():
            return None

        for wd in (C.metaOutDir, C.metaxOutDir):
            if not os.path.exists(wd):
                os.makedirs(wd, exist_ok=True)

        return True

    def doCommand(self, command, flag):
        getattr(self, command)(flag=flag)

    def collectPhotos(self):
        C = self.C

        if not os.path.exists(C.photosDir):
            console(f"Photos directory `{C.photosDir}` does not exist")
            return None

        allPhotos = []

        with os.scandir(C.photosDir) as it:
            for entry in it:
                fName = entry.name
                if (
                    fName.startswith(".")
                    or not fName.endswith(".jpg")
                    or not entry.is_file()
                ):
                    continue
                name = fName.removesuffix(".jpg")
                allPhotos.append(name)
            console(f"Found {len(allPhotos)} photos")
        allPhotos = tuple(sorted(allPhotos))
        self.allPhotos = allPhotos

        if C.photoName:
            if not os.path.exists(f"{C.photosDir}/{C.photoName}.jpg"):
                console(f"Specified photo `{C.photoName}` not found in {C.photosDir}")
                return None
            photos = (C.photoName,)
            console(f"Selected {C.photoName}")
        else:
            photos = allPhotos

        self.photos = photos
        return True

    def getKeywords(self):
        C = self.C
        defaults = C.metaDefaults

        allPhotos = self.allPhotos
        keywordSet = set(defaults["keywords"])
        allKeywordSet = set(defaults["keywords"])
        self.keywordSet = allKeywordSet
        self.allKeywordSet = allKeywordSet

        for name in allPhotos:
            inPath = f"{C.photosDir}/{name}.jpg"

            keywords = getPhotoMeta(inPath, defaults, True)["keywords"]
            allKeywordSet |= set(keywords)
            if name == C.photoName:
                keywordSet |= set(keywords)

    def getDates(self):
        C = self.C

        allPhotos = self.allPhotos
        photoDates = {}
        self.photoDates = photoDates

        for name in allPhotos:
            inPath = f"{C.metaDir}/{name}.yaml"

            if os.path.exists(inPath):
                logical = readYaml(inPath)
                sanitize(logical)
            else:
                logical = {}

            datetime = logical.get("datetime", "")
            photoDates[name] = datetime

    def importmeta(self, flag=None):
        C = self.C
        defaults = C.metaDefaults

        force = flag == "force" or C.photoName

        photos = self.photos

        unchanged = 0
        updated = 0

        console("Apply metadata ...")

        for name in photos:
            inPath = f"{C.metaDir}/{name}.yaml"
            outPath = f"{C.photosDir}/{name}.jpg"

            if not force:
                if not os.path.exists(inPath) or os.path.getmtime(
                    inPath
                ) <= os.path.getmtime(outPath):
                    unchanged += 1
                    continue

            if os.path.exists(inPath):
                logical = readYaml(inPath)
                sanitize(logical)
            else:
                logical = {}

            info = pyexiv2.ImageMetadata(outPath)
            info.read()

            actual = {}
            for (log, iName, eName) in METADATA:
                if log == "keywords":
                    val = sorted(set(logical.get(log, [])) | set(defaults[log]))
                else:
                    val = logical.get(log, None)
                    if val is None:
                        val = defaults.get(log, None)
                actual[log] = val

            if actual.get("source", None) is not None:
                actual["sourceAsUrl"] = urllib.parse.quote_plus(actual["source"])
            cpr = actual.get("copyright", None)
            caption = actual.get("caption", None)

            if cpr is not None:
                actual["copyright"] = cpr.format(**actual)
            colofon = C.colofon.format(**actual)

            if caption is None:
                actual["caption"] = f"{CAPTION_SEP}{colofon}"
            else:
                caption = COLOFON_RE.sub("", caption)
                actual["caption"] = f"{caption}{CAPTION_SEP}{colofon}"

            for (log, iName, eName) in METADATA:
                val = actual[log]
                if val is None:
                    continue
                if iName is not None:
                    info[iName] = val if log == "keywords" else [val]
                if eName is not None:
                    info[eName] = val
                if log == "datetime":
                    info[f"{eName}Original"] = val
                    (date, time) = val.split(" ")
                    date = date.replace(":", "-")
                    val = datetime.fromisoformat(f"{date}T{time}")
                    info["Iptc.Application2.DateCreated"] = [val]
                    info["Iptc.Application2.TimeCreated"] = [val]
                    info["Iptc.Application2.DigitizationDate"] = [val]
                    info["Iptc.Application2.DigitizationTime"] = [val]

            info.write()
            console(f"\tapplied to {name}")
            updated += 1
        console(
            f"""Import Metadata
Unchanged : {unchanged:>4}
Updated   : {updated:>4}
"""
        )

    def exportmeta(self, flag=None):
        expanded = flag == "full"
        C = self.C
        defaults = C.metaDefaults
        outDir = C.metaxOutDir if expanded else C.metaOutDir

        photos = self.photos

        for name in photos:
            inPath = f"{C.photosDir}/{name}.jpg"
            outPath = f"{outDir}/{name}.yaml"

            metadata = getPhotoMeta(inPath, defaults, expanded)

            with open(outPath, "w") as exh:
                yaml.dump(metadata, exh, allow_unicode=True)

    def flickr(self, flag=None):
        C = self.C
        defaults = C.metaDefaults

        force = flag == "force" or C.photoName

        photos = self.photos

        self.keywordSet = set()
        self.importmeta(flag)

        flickrUpdated = None if C.photoName else self.getFlickrUpdated()

        unchanged = 0
        updated = 0

        updates = []

        console("Update on Flickr ...")
        for name in photos:
            inPath = f"{C.photosDir}/{name}.jpg"
            if (
                not force
                and flickrUpdated
                and datetime.fromtimestamp(os.path.getmtime(inPath)) <= flickrUpdated
            ):
                unchanged += 1
                continue
            updates.append((name, inPath))

        console(f"\t{len(updates)} update{'' if len(updates) == 1 else 's'} needed")
        if updates:
            if not getattr(self, "albumFromId", None):
                self.flGetAlbums()

            for (name, inPath) in updates:
                metadata = getPhotoMeta(inPath, defaults, True)
                self.flPutAlbum(name, metadata)

            for (name, inPath) in updates:
                metadata = getPhotoMeta(inPath, defaults, True)
                self.flPutPhoto(name, metadata)
                console(f"\tupdated on flickr {name}")
                updated += 1

            self.flSortAlbums()

        if not C.photoName:
            self.setFlickrUpdated()
        console(
            f"""Synced with Flickr
Unchanged : {unchanged:>4}
Updated   : {updated:>4}
"""
        )

    def updatealbums(self, flag=None):
        C = self.C
        defaults = C.metaDefaults

        photos = self.photos

        self.keywordSet = set()

        albumStr = "all albums" if flag is None else f"albums {flag}"
        console(f"Update {albumStr} on Flickr ...")
        if not getattr(self, "albumFromId", None):
            self.flGetAlbums(contents=True, albums=flag)

        updated = 0
        unchanged = 0
        for name in photos:
            inPath = f"{C.photosDir}/{name}.jpg"
            metadata = getPhotoMeta(inPath, defaults, True)
            thisUpdated = self.flPutAlbum(name, metadata)
            if thisUpdated:
                updated += 1
            else:
                unchanged += 1

        self.wait()
        self.flSortAlbums()
        console(
            f"""Album assignments updated with Flickr
Unchanged : {unchanged:>4} photos
Updated   : {updated:>4} photos
"""
        )

    def sortalbums(self, flag=None):
        self.flConnect()

        albumStr = "all albums" if flag is None else f"albums {flag}"
        console(f"Sort {albumStr} on Flickr ...")
        if not getattr(self, "albumFromId", None):
            self.flGetAlbums(contents=False, albums=flag)

        albumFromId = self.albumFromId
        self.touchedAlbums = {
            albumId: albumTitle for (albumId, albumTitle) in albumFromId.items()
        }
        self.flSortAlbums()

    def flGetAlbums(self, contents=True, albums=None):
        C = self.C
        mainAlbum = C.albumName

        selectedAlbums = None if albums is None else set(albums.split(","))

        self.getKeywords()
        allKeywordSet = self.allKeywordSet

        self.flConnect()
        FL = self.FL

        allAlbums = FL.photosets.getList(user_id=C.flickrUserId)["photosets"][
            "photoset"
        ]
        idFromAlbum = {}
        albumFromId = {}
        albumsFromPhoto = {}
        photoFromId = {}
        idFromPhoto = {}
        self.photoFromId = photoFromId
        self.idFromPhoto = idFromPhoto
        self.idFromAlbum = idFromAlbum
        self.albumFromId = albumFromId
        self.albumsFromPhoto = albumsFromPhoto

        self.touchedAlbums = {}

        for album in allAlbums:
            albumTitle = album["title"]["_content"]
            if selectedAlbums is not None and albumTitle not in selectedAlbums:
                continue
            if albumTitle != mainAlbum and albumTitle.lower() not in allKeywordSet:
                continue
            albumId = album["id"]
            idFromAlbum[albumTitle] = albumId
            albumFromId[albumId] = albumTitle
            if albumTitle == mainAlbum:
                self.touchedAlbums[albumId] = albumTitle

        console("Albums on Flickr")
        for (albumId, albumTitle) in sorted(albumFromId.items(), key=lambda x: x[1]):
            isMain = albumTitle == mainAlbum

            if contents:
                albumPhotos = self.flGetPhotos(albumId)
                for photo in albumPhotos:
                    fileName = photo["title"]
                    if isMain:
                        photoId = photo["id"]
                        photoFromId[photoId] = fileName
                        idFromPhoto[fileName] = photoId
                    else:
                        albumsFromPhoto.setdefault(fileName, set()).add(albumTitle)
                console(f"\t{albumTitle:<25} {len(albumPhotos):>4} photos")
            else:
                console(f"\t{albumTitle}")

        console(f"\tTotal: {len(albumFromId):>4} albums on Flickr")
        if contents:
            console(f"\tTotal: {len(photoFromId):>4} photos on Flickr")
            console(f"\tTotal: {len(idFromPhoto):>4} titles on Flickr")

    def flGetPhotos(self, albumId):
        C = self.C
        FL = self.FL

        data = FL.photosets.getPhotos(user_id=C.flickrUserId, photoset_id=albumId)[
            "photoset"
        ]
        nPages = data["pages"]
        albumPhotos = data["photo"]
        if nPages > 1:
            for p in range(2, nPages + 1):
                data = FL.photosets.getPhotos(
                    user_id=C.flickrUserId, photoset_id=albumId, page=p
                )["photoset"]
                albumPhotos.extend(data["photo"])
        return albumPhotos

    def flPutPhoto(self, name, metadata):
        C = self.C
        FL = self.FL

        idFromPhoto = self.idFromPhoto

        photoId = idFromPhoto[name]
        inPath = f"{C.photosDir}/{name}.jpg"

        with open(inPath, "rb") as fh:
            FL.replace(inPath, photoId, fh, format="rest")
        description = metadata.get("caption", "")
        FL.photos.setMeta(photo_id=photoId, description=description)
        keywords = metadata.get("keywords", [])
        FL.photos.setTags(photo_id=photoId, tags=" ".join(keywords))

    def flPutAlbum(self, name, metadata):
        FL = self.FL
        touchedAlbums = self.touchedAlbums
        idFromPhoto = self.idFromPhoto
        idFromAlbum = self.idFromAlbum
        albumsFromPhoto = self.albumsFromPhoto
        C = self.C
        defaults = C.metaDefaults

        keywords = metadata.get("keywords", [])
        keywords = sorted(set(keywords) - set(defaults["keywords"]))
        albums = albumsFromPhoto.get(name, set())

        photoId = idFromPhoto[name]

        updated = 0
        for k in keywords:
            if k in albums:
                continue
            albumId = idFromAlbum.get(k, None)
            if albumId is None:
                console(f"\tmake new album {k}")
                albumId = self.flMakeAlbum(k, photoId)
            else:
                FL.photosets.addPhoto(photoset_id=albumId, photo_id=photoId)
            console(f"\tadded {name} to album {k}")
            updated = 1
            touchedAlbums[albumId] = k
        for a in albums:
            if a in keywords:
                continue
            albumId = idFromAlbum[a]
            FL.photosets.removePhoto(photoset_id=albumId, photo_id=photoId)
            console(f"\tremoved {name} from album {a}")
            updated = 1
        return updated

    def flSortAlbums(self):
        self.getDates()

        FL = self.FL

        touchedAlbums = self.touchedAlbums

        for (albumId, albumTitle) in sorted(touchedAlbums.items(), key=lambda x: x[1]):
            photos = sorted(self.flGetPhotos(albumId), key=self.byDate())
            console(f"\tsorting album {albumTitle} with {len(photos)} photos")
            photoIds = ",".join(photo["id"] for photo in photos)
            FL.photosets.reorderPhotos(photoset_id=albumId, photo_ids=photoIds)

    def byDate(self):
        photoDates = self.photoDates

        def dateKey(photo):
            name = photo["title"]
            return photoDates.get(name, "")

        return dateKey

    def flMakeAlbum(self, name, photoId):
        FL = self.FL
        albumFromId = self.albumFromId
        idFromAlbum = self.idFromAlbum

        result = FL.photosets.create(title=name, primary_photo_id=photoId)
        albumId = result["photoset"]["id"]
        albumFromId[albumId] = name
        idFromAlbum[name] = albumId
        return albumId

    def flConnect(self):
        C = self.C
        if not getattr(self, "FL", None):
            FL = flickrapi.FlickrAPI(
                C.flickrKey, C.flickrSecret, format="parsed-json", cache=CACHE
            )

            if not FL.token_valid(perms="write"):
                FL.get_request_token(oauth_callback="oob")
                authorize_url = FL.auth_url(perms="write")
                webbrowser.open_new_tab(authorize_url)
                verifier = str(input("Verifier code: "))
                FL.get_access_token(verifier)
            self.FL = FL

    def wait(self):
        # there is caching in flickr that interferes with adding photos to albums

        delay = 10
        del self.FL
        console(f"Waiting {delay} seconds  for Flickr to settle the changes")
        sleep(delay)
        self.flConnect()

    def getFlickrUpdated(self):
        flickrUpdated = None
        if os.path.exists(FLICKR_UPDATED):
            with open(FLICKR_UPDATED) as fh:
                flickrUpdated = fh.read()
            flickrUpdated = datetime.fromisoformat(flickrUpdated.strip())
            console(f"Flickr last updated on {flickrUpdated.isoformat()}")
        else:
            console("Flickr not previously updated")
        return flickrUpdated

    def setFlickrUpdated(self):
        with open(FLICKR_UPDATED, "w") as fh:
            fh.write(datetime.now().isoformat())


def main():
    A = readArgs()
    if A is None:
        return 0

    source = A.source
    name = A.name
    command = A.command
    flag = A.flag

    if not source:
        return

    Mk = Make(source, name)

    return Mk.doCommand(command, flag=flag)


if __name__ == "__main__":
    sys.exit(main())
