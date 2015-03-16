# distbuild/timer_event_source.py -- event source for timer events
#
# Copyright (C) 2012, 2014-2015  Codethink Limited
# 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program.  If not, see <http://www.gnu.org/licenses/>.


import time


class Timer(object):

    pass


class TimerEventSource(object):

    def __init__(self, interval):
        self.interval = interval
        self.last_event = time.time()
        self.enabled = False

    def start(self):
        self.enabled = True
        self.last_event = time.time()
        
    def stop(self):
        self.enabled = False
        
    def get_select_params(self):
        if self.enabled:
            next_event = self.last_event + self.interval
            timeout = next_event - time.time()
            return [], [], [], max(0, timeout)
        else:
            return [], [], [], None

    def get_events(self, r, w, x):
        if self.enabled:
            now = time.time()
            if now >= self.last_event + self.interval:
                self.last_event = now
                return [Timer()]
        return []

    def is_finished(self):
        return False

