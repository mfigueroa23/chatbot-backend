from getpass import getpass
from src.services.executive_auth import password_hasher

def main() -> None:
    password = getpass("Contraseña del ejecutivo: ")
    if not password:
        raise SystemExit("La contraseña no puede estar vacía")
    print(password_hasher.hash(password))

if __name__ == "__main__":
    main()
