import re
import os
import sys
import urllib
from datetime import datetime
from time import sleep
import fractions
from math import modf
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
    export defined metadata from photos to a local directory,
    if `full` is passed, also export default/computed values.
""",
    exportmetafull="""
    export full metadata from photos to the dropbox directory,
    Full means: with default values and computed values.
    Only when the photo is newer than the metadata file.
    But when force, do all photos.
""",
    sync="""
    sync updates to Flickr, including metadata and album membership;
    if force, sync all photos".
    Also export metadata of changed photos in full.
""",
    albumsort="""
    sort existing albums on Flickr; do not sync metadata and album changes.
    You can pass a comma-separated list of albums to sort.
""",
    albumsync="""
    sync album memberships to Flickr, do not sync metadata changes.
    You can pass a comma-separated list of albums to sync.
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
        of the Flickr update will be ignored and not updated.

command flag:
{COMMAND_STR}

If no command is given, `sync` is assumed.

-h
--help
help  : print help and exit
"""


REPO_DIR = f"{os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}"
LOCAL_DIR = f"{REPO_DIR}/_local"
FLICKR_CONFIG = f"{LOCAL_DIR}/flickr.yaml"
FLICKR_UPDATED_FILE = "flickrupdated.txt"


METADATA = (
    ("source", "Iptc.Application2.Source", None),
    ("credit", "Iptc.Application2.Credit", None),
    ("copyright", "Iptc.Application2.Copyright", "Exif.Image.Copyright"),
    ("author", "Iptc.Application2.Byline", "Exif.Image.Artist"),
    ("writer", "Iptc.Application2.Writer", None),
    ("caption", "Iptc.Application2.Caption", "Exif.Image.ImageDescription"),
    ("keywords", "Iptc.Application2.Keywords", None),
    ("datetime", None, "Exif.Image.DateTime"),
    ("location", None, None),
)
EXIF_DATE = METADATA[-1][-1]
GPS = "Exif.GPSInfo.GPS"

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
        A.command = "sync"
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
            flag == "full"
            and command != "exportmeta"
            or flag == "force"
            and command not in {"importmeta", "exportmetafull", "sync"}
            or flag not in {"full", "force"}
        ):
            console(HELP)
            console(f"Unknown flag `{flag}` for command `{command}`")
            return None

    A.flag = flag

    if command not in COMMANDS:
        console(HELP)
        console(f"Wrong command: ??{' '.join(args)}??")
        return None

    return A


def readYaml(path):
    with open(path) as fh:
        settings = yaml.load(fh, Loader=yaml.FullLoader)
    return settings


def getPhotoDate(inPath):
    info = pyexiv2.ImageMetadata(inPath)
    info.read()
    eNames = set(info.exif_keys)
    eName = EXIF_DATE
    eNameOrig = f"{eName}Original"
    val = "" if eNameOrig not in eNames else info[eNameOrig].raw_value
    if not val:
        val = "" if eName not in eNames else info[eName].raw_value
    return val


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
        elif log == "location":
            val = getGPS(info)
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


class Fraction(fractions.Fraction):
    """Only create Fractions from floats.

    >>> Fraction(0.3)
    Fraction(3, 10)
    >>> Fraction(1.1)
    Fraction(11, 10)
    """

    def __new__(cls, value, ignore=None):
        """Should be compatible with Python 2.6, though untested."""
        return fractions.Fraction.from_float(value).limit_denominator(99999)


def dms_to_decimal(degrees, minutes, seconds, sign=" "):
    """Convert degrees, minutes, seconds into decimal degrees.

    >>> dms_to_decimal(10, 10, 10)
    10.169444444444444
    >>> dms_to_decimal(8, 9, 10, 'S')
    -8.152777777777779
    """
    return (-1 if sign[0] in "SWsw" else 1) * (
        float(degrees) + float(minutes) / 60 + float(seconds) / 3600
    )


def decimal_to_dms(decimal):
    """Convert decimal degrees into degrees, minutes, seconds.

    >>> decimal_to_dms(50.445891)
    [Fraction(50, 1), Fraction(26, 1), Fraction(113019, 2500)]
    >>> decimal_to_dms(-125.976893)
    [Fraction(125, 1), Fraction(58, 1), Fraction(92037, 2500)]
    """
    remainder, degrees = modf(abs(decimal))
    remainder, minutes = modf(remainder * 60)
    return [Fraction(n) for n in (degrees, minutes, remainder * 60)]


def getGPS(info):
    try:
        latitude = dms_to_decimal(
            *info[GPS + "Latitude"].value + [info[GPS + "LatitudeRef"].value]
        )
        longitude = dms_to_decimal(
            *info[GPS + "Longitude"].value + [info[GPS + "LongitudeRef"].value]
        )
    except KeyError:
        latitude = ""
        longitude = ""
    try:
        altitude = float(info[GPS + "Altitude"].value)
        if int(info[GPS + "AltitudeRef"].value) > 0:
            altitude *= -1
    except KeyError:
        altitude = ""
    return f"lat={latitude} lng={longitude} alt={altitude}"


LAT_RE = re.compile(r"lat=(\S*)")
LNG_RE = re.compile(r"lng=(\S*)")
ALT_RE = re.compile(r"alt=(\S*)")


def putGPS(val, info):
    for (field, fieldRe, refVals) in (
        ("Latitude", LAT_RE, ("N", "S")),
        ("Longitude", LNG_RE, ("E", "W")),
        ("Altitude", ALT_RE, ("0", "1")),
    ):
        fieldVal = fieldRe.findall(val)
        if len(fieldVal):
            fieldVal = fieldVal[0]
            if fieldVal:
                fieldVal = float(fieldVal)
                info[f"{GPS}{field}"] = decimal_to_dms(fieldVal)
                info[f"{GPS}{field}Ref"] = refVals[0] if fieldVal >= 0 else refVals[1]
    info[f"{GPS}MapDatum"] = "WGS-84"


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
        c["metafOutDir"] = f"{IMAGE_BASE}/{source}/metadatafull"

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

        for wd in (C.metaOutDir, C.metaxOutDir, C.metafOutDir):
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
            yamlFile = f"{C.metaDir}/{name}.yaml"

            if os.path.exists(yamlFile):
                logical = readYaml(yamlFile)
                sanitize(logical)
            else:
                logical = {}

            datetime = logical.get(
                "datetime", getPhotoDate(f"{C.photosDir}/{name}.jpg")
            )
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
                elif log == "location":
                    putGPS(val, info)

            info.write()
            console(f"\tapplied to {name}")
            updated += 1
        console(
            f"""Import Metadata
Unchanged : {unchanged:>4}
Updated   : {updated:>4}
"""
        )

    def exportmetafull(self, flag=None):
        C = self.C
        defaults = C.metaDefaults
        outDir = C.metafOutDir

        photos = self.photos

        force = flag == "force" or C.photoName

        unchanged = 0
        updated = 0

        console("Generate full metadata ...")

        for name in photos:
            inPath = f"{C.photosDir}/{name}.jpg"
            outPath = f"{outDir}/{name}.yaml"

            if not force:
                if not os.path.exists(inPath) or (
                    os.path.exists(outPath)
                    and os.path.getmtime(inPath) <= os.path.getmtime(outPath)
                ):
                    unchanged += 1
                    continue

            metadata = getPhotoMeta(inPath, defaults, True)

            with open(outPath, "w") as exh:
                yaml.dump(metadata, exh, allow_unicode=True)

            updated += 1

        console(
            f"""Write Metadata Full
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

    def sync(self, flag=None):
        C = self.C
        defaults = C.metaDefaults

        force = flag == "force" or C.photoName

        photos = self.photos

        self.keywordSet = set()
        self.importmeta(flag)
        self.exportmetafull(flag=flag)

        flickrUpdated = None if C.photoName else self.getFlickrUpdated()

        updates = []

        console("Update on Flickr ...")
        for name in photos:
            inPath = f"{C.photosDir}/{name}.jpg"
            if (
                not force
                and flickrUpdated
                and datetime.fromtimestamp(os.path.getmtime(inPath)) <= flickrUpdated
            ):
                continue
            updates.append((name, inPath))

        console(f"\t{len(updates)} update{'' if len(updates) == 1 else 's'} needed")
        if updates:
            if not getattr(self, "albumFromId", None):
                self.flGetAlbums(touchMain=True)

            console("Sync photo updates with Flickr")
            for (name, inPath) in updates:
                metadata = getPhotoMeta(inPath, defaults, True)
                self.flPutPhoto(name, metadata)
                console(f"\tupdated on Flickr {name}")

            self.albumAdditions = {}
            self.albumDeletions = {}

            unchanged = 0
            updated = 0

            for (name, inPath) in updates:
                metadata = getPhotoMeta(inPath, defaults, True)
                thisUpdated = self.flPutAlbum(name, metadata, detectMetaChange=True)
                if thisUpdated:
                    updated += 1
                else:
                    unchanged += 1

            console(
                f"""Get album membership changes:
Unchanged : {unchanged:>4} photos
Updated   : {updated:>4} photos
"""
            )
            self.flApplyAlbums()

        if not C.photoName:
            self.setFlickrUpdated()
        updated = len(updates)
        unchanged = len(photos) - updated
        console(
            f"""Synced with Flickr
Unchanged : {unchanged:>4}
Updated   : {updated:>4}
"""
        )

    def albumsync(self, flag=None):
        C = self.C
        defaults = C.metaDefaults

        photos = self.photos

        self.keywordSet = set()

        albumStr = "all albums" if flag is None else f"albums {flag}"
        console(f"Update {albumStr} on Flickr ...")
        if not getattr(self, "albumFromId", None):
            self.flGetAlbums(contents=True, albums=flag, touchMain=False)

        updated = 0
        unchanged = 0
        self.albumAdditions = {}
        self.albumDeletions = {}

        for name in photos:
            inPath = f"{C.photosDir}/{name}.jpg"
            metadata = getPhotoMeta(inPath, defaults, True)
            thisUpdated = self.flPutAlbum(name, metadata, detectMetaChange=False)
            if thisUpdated:
                updated += 1
            else:
                unchanged += 1

        console(
            f"""Photo memberships of albums:
Unchanged : {unchanged:>4}
Updated   : {updated:>4}
"""
        )
        self.flApplyAlbums()

    def albumsort(self, flag=None):
        self.flConnect()
        FL = self.FL

        albumStr = "all albums" if flag is None else f"albums {flag}"
        console(f"Sort {albumStr} on Flickr ...")
        if not getattr(self, "albumFromId", None):
            self.flGetAlbums(contents=False, albums=flag, touchMain=False)

        albumFromId = self.albumFromId

        for (albumId, albumTitle) in sorted(albumFromId.items(), key=lambda x: x[1]):
            photos = sorted(
                self.flGetPhotos(albumId, withDates=True),
                key=lambda p: p.get("datetaken", ""),
            )
            console(f"\tsorting album {albumTitle} with {len(photos)} photos")
            photoIds = ",".join(photo["id"] for photo in photos)
            self.wait()
            FL.photosets.reorderPhotos(photoset_id=albumId, photo_ids=photoIds)

    def flGetAlbums(self, contents=True, albums=None, touchMain=True):
        C = self.C
        mainAlbum = C.albumName

        selectedAlbums = None if albums is None else set(albums.split(","))

        self.getKeywords()
        allKeywordSet = self.allKeywordSet

        self.flConnect()
        FL = self.FL

        self.wait()
        allAlbums = FL.photosets.getList(user_id=C.flickrUserId)["photosets"][
            "photoset"
        ]
        idFromAlbum = {}
        albumFromId = {}
        albumPrimary = {}
        albumPhotos = {}
        albumsFromPhoto = {}
        nameFromId = {}
        idFromName = {}
        self.nameFromId = nameFromId
        self.idFromName = idFromName
        self.idFromAlbum = idFromAlbum
        self.albumFromId = albumFromId
        self.albumsFromPhoto = albumsFromPhoto
        self.albumPrimary = albumPrimary
        self.albumPhotos = albumPhotos

        self.touchedAlbums = {}

        for album in allAlbums:
            albumTitle = album["title"]["_content"]
            primary = album["primary"]
            albumPrimary[albumTitle] = primary
            if selectedAlbums is not None and albumTitle not in selectedAlbums:
                continue
            if albumTitle != mainAlbum and albumTitle.lower() not in allKeywordSet:
                continue
            albumId = album["id"]
            idFromAlbum[albumTitle] = albumId
            albumFromId[albumId] = albumTitle
            if touchMain and albumTitle == mainAlbum:
                self.touchedAlbums[albumId] = albumTitle

        console("Albums on Flickr")
        for (albumId, albumTitle) in sorted(albumFromId.items(), key=lambda x: x[1]):
            isMain = albumTitle == mainAlbum

            if contents:
                photos = self.flGetPhotos(albumId, withDates=False)
                for photo in photos:
                    fileName = photo["title"]
                    if isMain:
                        photoId = photo["id"]
                        nameFromId[photoId] = fileName
                        idFromName[fileName] = photoId
                    else:
                        albumsFromPhoto.setdefault(fileName, set()).add(albumTitle)
                    albumPhotos.setdefault(albumTitle, set()).add(fileName)
                console(f"\t{albumTitle:<25} {len(photos):>4} photos")
            else:
                console(f"\t{albumTitle}")

        console(f"\tTotal: {len(albumFromId):>4} albums on Flickr")
        if contents:
            console(f"\tTotal: {len(nameFromId):>4} photos on Flickr")
            console(f"\tTotal: {len(idFromName):>4} titles on Flickr")

    def flGetPhotos(self, albumId, withDates=False):
        C = self.C
        FL = self.FL

        self.wait()
        extras = dict(extras="date_taken") if withDates else {}
        data = FL.photosets.getPhotos(
            user_id=C.flickrUserId, photoset_id=albumId, **extras
        )["photoset"]
        nPages = data["pages"]
        photos = data["photo"]
        if nPages > 1:
            for p in range(2, nPages + 1):
                self.wait()
                data = FL.photosets.getPhotos(
                    user_id=C.flickrUserId, photoset_id=albumId, page=p, **extras
                )["photoset"]
                photos.extend(data["photo"])
        return photos

    def flPutPhoto(self, name, metadata):
        C = self.C
        FL = self.FL

        idFromName = self.idFromName

        photoId = idFromName[name]
        inPath = f"{C.photosDir}/{name}.jpg"

        with open(inPath, "rb") as fh:
            self.wait()
            FL.replace(inPath, photoId, fh, format="rest")
        description = metadata.get("caption", "")
        self.wait()
        FL.photos.setMeta(photo_id=photoId, description=description)
        keywords = metadata.get("keywords", [])
        self.wait()
        FL.photos.setTags(photo_id=photoId, tags=" ".join(keywords))

    def flPutAlbum(self, name, metadata, detectMetaChange=True):
        idFromAlbum = self.idFromAlbum
        albumsFromPhoto = self.albumsFromPhoto
        albumAdditions = self.albumAdditions
        albumDeletions = self.albumDeletions
        touchedAlbums = self.touchedAlbums
        C = self.C
        defaults = C.metaDefaults

        keywords = metadata.get("keywords", [])
        keywords = sorted(set(keywords) - set(defaults["keywords"]))
        albums = albumsFromPhoto.get(name, set())

        updated = 0

        for k in keywords:
            if detectMetaChange:
                albumId = idFromAlbum.get(k, None)
                if albumId is not None:
                    touchedAlbums[albumId] = k
                # if albumId is None, a new album will be made,
                # it will be included in albumAdditions
                # and hence it will enter the touched albums as well
                updated = 1

            if k in albums:
                continue
            updated = 1
            albumAdditions.setdefault(k, []).append(name)

        for a in albums:
            if a in keywords:
                continue
            albumDeletions.setdefault(a, []).append(name)
            updated = 1

        return updated

    def flApplyAlbums(self):
        FL = self.FL
        albumAdditions = self.albumAdditions
        albumDeletions = self.albumDeletions
        touchedAlbums = self.touchedAlbums
        idFromAlbum = self.idFromAlbum
        idFromName = self.idFromName
        nameFromId = self.nameFromId
        albumFromId = self.albumFromId
        albumPhotos = self.albumPhotos
        albumPrimary = self.albumPrimary

        console("Collect photos to add to albums")

        for (album, names) in sorted(albumAdditions.items()):
            albumId = idFromAlbum.get(album, None)
            newalbum = "new " if albumId is None else ""
            plural = "" if len(names) == 1 else "s"
            console(f"\tadd to {newalbum}{album}: {len(names)} photo{plural}")

            for name in names:
                console(f"\t\t{name}")
                photoId = idFromName[name]
                if albumId is None:
                    albumId = self.flMakeAlbum(album, photoId)
                    idFromAlbum[album] = albumId
                    albumFromId[albumId] = album
                    albumPhotos[album] = {name}
                    albumPrimary[album] = photoId
                else:
                    albumPhotos[album].add(name)

            touchedAlbums[albumId] = album

        console("Collect photos to remove from albums")

        for (album, names) in sorted(albumDeletions.items()):
            albumId = idFromAlbum.get(album, None)
            if albumId is None:
                namesStr = ", ".join(names)
                console(
                    f"\twarning: trying to remove {namesStr} from empty album {album}"
                )
                continue

            touchedAlbums[albumId] = album
            plural = "" if len(names) == 1 else "s"
            console(f"\tremove from {album}: {len(names)} photo{plural}")

            for name in names:
                console(f"\t\t{name}")
                albumPhotos[album].discard(name)

        if touchedAlbums:
            console("Sync album changes with Flickr")
            self.getDates()
            photoDates = self.photoDates

            for (albumId, album) in sorted(touchedAlbums.items()):
                primary = albumPrimary[album]
                primaryName = nameFromId[primary]
                names = sorted(albumPhotos[album], key=lambda n: photoDates[n])
                if primaryName not in albumPhotos[album]:
                    primaryName = names[0]
                    primary = idFromName[primaryName]
                plural = "" if len(names) == 1 else "s"
                console(f"\tsyncing {album}: {len(names)} photo{plural}")
                photoIds = ",".join(idFromName[name] for name in names)
                self.wait()
                FL.photosets.editPhotos(
                    photoset_id=albumId, primary_photo_id=primary, photo_ids=photoIds
                )
        else:
            console("No album changes to sync with Flickr")

    def flMakeAlbum(self, name, photoId):
        FL = self.FL
        albumFromId = self.albumFromId
        idFromAlbum = self.idFromAlbum

        self.wait()
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
        sys.stdout.write(".")
        delay = 0.2
        sleep(delay)

    def getFlickrUpdated(self):
        source = self.source
        flickrUpdated = None
        flUpdatePath = f"{LOCAL_DIR}/{source}-{FLICKR_UPDATED_FILE}"
        if os.path.exists(flUpdatePath):
            with open(flUpdatePath) as fh:
                flickrUpdated = fh.read()
            flickrUpdated = datetime.fromisoformat(flickrUpdated.strip())
            console(f"Flickr last updated on {flickrUpdated.isoformat()}")
        else:
            console("Flickr not previously updated")
        return flickrUpdated

    def setFlickrUpdated(self):
        source = self.source
        flUpdatePath = f"{LOCAL_DIR}/{source}-{FLICKR_UPDATED_FILE}"
        with open(flUpdatePath, "w") as fh:
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
