#!/bin/bash

FILES="$(find ./mesh -name '*.py' | tr '\n' ' ')"

autopep8 -ia --ignore=E501 ${FILES}
