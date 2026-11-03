"""Reports: the analytics the engine computed, arranged and serialised.

    analytics contracts -> model.Report -> csv / xlsx / pdf bytes

builders reads the analytics contracts and lays them out; the exporters serialise the
result and calculate nothing. One report object feeds all three formats, which is why they
agree and why proving it is a test rather than a promise.
"""
