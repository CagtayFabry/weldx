.. _standard:

Standard
========

Schema Definitions
##################

The WelDX standard consists of the following schema definitions:

.. toctree::
    :maxdepth: 2

    schemas/core.rst
    schemas/equipment.rst
    schemas/measurement.rst
    schemas/process.rst
    schemas/time.rst
    schemas/groove.rst
    schemas/aws.rst
    schemas/datamodels.rst
    schemas/generic.rst

Manifests
#########

The WelDX manifests map the supported tag and schema URIs.

.. asdf-autoschemas::

    manifests/*

ASDF Extension
##############

The WelDX ASDF Extension implements some additional functionalities like unit and shape validation for specific objects.

.. toctree::
    :maxdepth: 1

    standard/validators
    standard/shape-validation
    standard/unit-validation
    standard/welding-processes
