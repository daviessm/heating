#!/bin/bash
kill `ps aux | grep heating | grep python | awk '{ print $2 }'`
