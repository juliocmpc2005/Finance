"""Local account recovery. Run on the machine holding the database."""
import argparse
import getpass
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from backend import auth


def main():
    parser=argparse.ArgumentParser(description='Recuperación local de cuentas de ADG Finance')
    sub=parser.add_subparsers(dest='action',required=True)
    sub.add_parser('reset-password',help='Crear una contraseña temporal').add_argument('email')
    sub.add_parser('revoke-sessions',help='Cerrar todas las sesiones, por ejemplo al trasladar el servidor')
    args=parser.parse_args();data=Path(os.environ.get('ADG_DATA_DIR',Path(__file__).resolve().parent/'data'));database=data/'finance.sqlite'
    if not database.exists():parser.error('No se encuentra la base de datos de esta empresa.')
    with closing(sqlite3.connect(database)) as c,c:
        c.row_factory=sqlite3.Row
        if args.action=='revoke-sessions':
            c.execute('DELETE FROM sessions');auth.audit(c,None,'Cerrar todas las sesiones desde la recuperación local');print('Todas las sesiones se han cerrado.');return
        user=c.execute('SELECT * FROM users WHERE email=?',(args.email.strip().casefold(),)).fetchone()
        if not user:parser.error('No existe una cuenta con ese correo.')
        password=getpass.getpass('Nueva contraseña temporal (mínimo 6 caracteres): ')
        if password!=getpass.getpass('Repite la contraseña temporal: '):parser.error('Las contraseñas no coinciden.')
        try:encoded=auth.password_hash(password)
        except ValueError as error:parser.error(str(error))
        c.execute('UPDATE users SET password_hash=?,must_change_password=1 WHERE id=?',(encoded,user['id']))
        c.execute('DELETE FROM sessions WHERE user_id=?',(user['id'],));auth.audit(c,None,'Restablecer contraseña mediante recuperación local: '+user['name'])
        print('Contraseña temporal guardada. La persona elegirá una personal al volver a entrar.')

if __name__=='__main__':main()
