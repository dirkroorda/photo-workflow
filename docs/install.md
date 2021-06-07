# Installation

## Dependency

We need to install `py3exiv2`.

Install
[homebrew](https://brew.sh)
if you do not have it.

Then:

```
brew install boost-python3 gexiv2 pygobject3
```

Download the
[py3exiv2](https://pypi.org/project/py3exiv2/#files)
package.
Go to the directory where you have downloaded this and do

```
pip3 install py3exiv2-{version_number}.tar.gz
```

See also:

*   [Source of above instructions](https://www.rwardrup.com/install-py3exiv2-on-macos/).
*   [py3exiv2 docs](https://python3-exiv2.readthedocs.io/en/latest/index.html)

## Updatr

In order to install the **updatr** package:

```
git clone https://github.com/dirkroorda/photo-workflow
cd photo-workflow

pip3 install -e .
```

## Usage

You now have a command `updatr`.

Do

```
updatr
```

to get help on how to run update commands on sources and works within sources.
Or read [usage](usage.md)...
