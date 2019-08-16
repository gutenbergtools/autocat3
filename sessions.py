# will submit a PR to CherryPy project - if it gets merged we can remove it. ESH 8/15/2019
import cherrypy
from cherrypy.lib.sessions import RamSession as cpRamSession

class RamSession(cpRamSession):
    def clean_up(self):
        """Clean up expired sessions."""

        now = self.now()
        try:
            cache_items_copy = self.cache.copy().items()
        except RuntimeError as re:
            """Under heavy load, list(self.cache.items()) will occasionally raise this error
            for large session caches with message "dictionary changed size during iteration"
            Better to pause the cleanup than to let the cleanup thread die.
            """
            cherrypy.log(f'Runtime Error happened while copying the cache entries: {re}')
            cherrypy.log('Ref: https://github.com/cherrypy/cherrypy/pull/1804')
            return

        for _id, (data, expiration_time) in cache_items_copy:
            if expiration_time <= now:
                try:
                    del self.cache[_id]
                except KeyError:
                    pass
                try:
                    if self.locks[_id].acquire(blocking=False):
                        lock = self.locks.pop(_id)
                        lock.release()
                except KeyError:
                    pass


            return 

        # added to remove obsolete lock objects
        for _id in list(self.locks):
            locked = (
                _id not in self.cache
                and self.locks[_id].acquire(blocking=False)
            )
            if locked:
                lock = self.locks.pop(_id)
                lock.release()
