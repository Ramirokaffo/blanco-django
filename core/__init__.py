"""
Core application initialization.
Configure PyMySQL as MySQL driver.
"""

import pymysql

# Use PyMySQL as MySQLdb replacement
pymysql.install_as_MySQLdb()

# Bypass version check
pymysql.version_info = (2, 2, 1, "final", 0)
