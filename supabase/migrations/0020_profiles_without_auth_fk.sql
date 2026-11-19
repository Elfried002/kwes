-- 0020 — Le profil n'est plus une copie de auth.users
--
-- Depuis la migration vers un PostgreSQL dédié, l'authentification est assurée
-- par Supabase Cloud : les nouveaux comptes existent dans SON schéma auth, pas
-- dans celui de notre base. La clé étrangère `profiles.id -> auth.users(id)`
-- faisait donc échouer la création du profil à la première connexion, et l'API
-- répondait 401 « Profil introuvable » — pour Google comme pour e-mail/mot de
-- passe.
--
-- L'autorité d'identité est la signature du jeton (ES256, JWKS Supabase),
-- vérifiée par l'API. La table locale n'a pas à dupliquer auth.users.

alter table profiles drop constraint if exists profiles_id_fkey;
