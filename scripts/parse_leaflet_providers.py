"""
Script to parse the tile providers defined by the leaflet-providers.js
extension to Leaflet (https://github.com/leaflet-extras/leaflet-providers).

It accesses the defined TileLayer.Providers objects through javascript
using Selenium as JSON, and then processes this a fully specified
javascript-independent dictionary and saves that final result as a JSON file.

"""
import datetime
import json
import os
import tempfile
import textwrap

import selenium.webdriver
import git


GIT_URL = "https://github.com/leaflet-extras/leaflet-providers.git"


# -----------------------------------------------------------------------------
# Downloading and processing the json data


def get_json_data():
    with tempfile.TemporaryDirectory() as tmpdirname:
        repo = git.Repo.clone_from(GIT_URL, tmpdirname)
        commit_hexsha = repo.head.object.hexsha
        commit_message = repo.head.object.message

        index_path = "file://" + os.path.join(tmpdirname, "index.html")

        driver = selenium.webdriver.Firefox()
        driver.get(index_path)
        data = driver.execute_script(
            "return JSON.stringify(L.TileLayer.Provider.providers)"
        )
        driver.close()

    data = json.loads(data)
    description = "commit {0} ({1})".format(commit_hexsha, commit_message.strip())

    return data, description


def process_data(data):
    # extract attributions from rawa data that later need to be substituted
    global ATTRIBUTIONS
    ATTRIBUTIONS = {
        "{attribution.OpenStreetMap}": data["OpenStreetMap"]["options"]["attribution"],
        "{attribution.Esri}": data["Esri"]["options"]["attribution"],
        "{attribution.OpenMapSurfer}": data["OpenMapSurfer"]["options"]["attribution"],
    }

    result = {}
    for provider in data:
        result[provider] = process_provider(data, provider)
    return result


def process_provider(data, name="OpenStreetMap"):
    provider = data[name].copy()
    variants = provider.pop("variants", None)
    options = provider.pop("options")
    provider_keys = {**provider, **options}

    if variants is None:
        provider_keys["name"] = name
        provider_keys = pythonize_data(provider_keys)
        return provider_keys

    result = {}

    for variant in variants:
        var = variants[variant]
        if isinstance(var, str):
            variant_keys = {"variant": var}
        else:
            variant_keys = var.copy()
            variant_options = variant_keys.pop("options", {})
            variant_keys = {**variant_keys, **variant_options}
        variant_keys = {**provider_keys, **variant_keys}
        variant_keys["name"] = "{provider}.{variant}".format(
            provider=name, variant=variant
        )
        variant_keys = pythonize_data(variant_keys)
        result[variant] = variant_keys

    return result


def pythonize_data(data):
    """
    Clean-up the javascript based dictionary:
    - rename mixedCase keys
    - substitute the attribution placeholders

    """
    rename_keys = {"maxZoom": "max_zoom", "minZoom": "min_zoom"}
    attributions = ATTRIBUTIONS

    items = data.items()

    new_data = []
    for key, value in items:
        if (key == "attribution") and ("{attribution." in value):
            for placeholder, attr in attributions.items():
                if placeholder in value:
                    value = value.replace(placeholder, attr)
                    if "{attribution." not in value:
                        # replaced last attribution
                        break
            else:
                raise ValueError("Attribution not known: {}".format(value))
        elif key in rename_keys:
            key = rename_keys[key]
        elif key == "url" and any(k in value for k in rename_keys):
            # NASAGIBS providers have {maxZoom} in the url
            for old, new in rename_keys.items():
                value = value.replace("{" + old + "}", "{" + new + "}")
        new_data.append((key, value))

    return dict(new_data)


# -----------------------------------------------------------------------------
# Generating a python file from the json

template = '''\
"""
Tile providers.

This file is autogenerated! It is a python representation of the leaflet
providers defined by the leaflet-providers.js extension to Leaflet
(https://github.com/leaflet-extras/leaflet-providers).
Credit to the leaflet-providers.js  project (BSD 2-Clause "Simplified" License)
and the Leaflet Providers contributors.

Generated by parse_leaflet_providers.py at {timestamp} from leaflet-providers
at {description}.

"""


class Bunch(dict):
    """A dict with attribute-access"""

    def __getattr__(self, key):
        try:
            return self.__getitem__(key)
        except KeyError:
            raise AttributeError(key)

    def __dir__(self):
        return self.keys()


class TileProvider(Bunch):
    """
    A dict with attribute-access and that
    can be called to update keys
    """

    def __call__(self, **kwargs):
        new = TileProvider(self)  # takes a copy preserving the class
        new.update(kwargs)
        return new


providers = Bunch(
{providers}
)

'''


def format_provider(data, name):
    formatted_keys = ",\n    ".join(
        [
            "{key} = {value!r}".format(key=key, value=value)
            for key, value in data.items()
        ]
    )
    provider_template = """\
{name} = TileProvider(
    {formatted_keys}
)"""
    return provider_template.format(name=name, formatted_keys=formatted_keys)


def format_bunch(data, name):
    bunch_template = """\
{name} = Bunch(
{variants}
)"""
    return bunch_template.format(name=name, variants=textwrap.indent(data, "    "))


def generate_file(data, description):
    providers = []

    for provider_name in data.keys():
        provider = data[provider_name]
        if "url" in provider.keys():
            res = format_provider(provider, provider_name)
        else:
            variants = []

            for variant in provider:
                formatted = format_provider(provider[variant], variant)
                variants.append(formatted)

            variants = ",\n".join(variants)
            res = format_bunch(variants, provider_name)

        providers.append(res)

    providers = ",\n".join(providers)
    content = template.format(
        providers=textwrap.indent(providers, "    "),
        description=description,
        timestamp=datetime.date.today(),
    )
    return content


if __name__ == "__main__":
    data, description = get_json_data()
    with open("leaflet-providers-raw.json", "w") as f:
        json.dump(data, f)

    # with open("leaflet-providers-raw.json", "r") as f:
    #     data = json.load(f)
    # description = ''

    result = process_data(data)
    with open("leaflet-providers-parsed.json", "w") as f:
        # wanted to add this as header to the file, but JSON does not support
        # comments
        print(
            "JSON representation of the leaflet providers defined by the "
            "leaflet-providers.js extension to Leaflet "
            "(https://github.com/leaflet-extras/leaflet-providers)"
        )
        print("This file is automatically generated from {}".format(description))
        json.dump(result, f)

    content = generate_file(result, description)
    with open("_providers.py", "w") as f:
        f.write(content)
