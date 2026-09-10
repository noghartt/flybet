{
  description = "Flybet — full MaleCNS v1.0, simulated money, live neural telemetry";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "aarch64-darwin"
        "aarch64-linux"
        "x86_64-linux"
      ];
      eachSystem = nixpkgs.lib.genAttrs systems;
      forSystem =
        system:
        let
          pkgs = import nixpkgs { inherit system; };
          python = pkgs.python312;
          runtime =
            ps: with ps; [
              numpy
              pandas
              pyarrow
              pillow
              fastapi
              uvicorn
            ];
          development =
            ps:
            runtime ps
            ++ (with ps; [
              pytest
              httpx
            ]);
          app = python.pkgs.buildPythonApplication {
            pname = "flybet";
            version = "0.1.0";
            pyproject = true;
            src = pkgs.lib.cleanSourceWith {
              src = ./.;
              filter =
                path: type:
                let
                  name = baseNameOf path;
                in
                !(builtins.elem name [
                  "data"
                  "runs"
                  ".venv"
                  ".direnv"
                  ".git"
                  ".cache"
                  "__pycache__"
                  ".pytest_cache"
                  ".ruff_cache"
                  "result"
                  "build"
                  "dist"
                ])
                && !(pkgs.lib.hasSuffix ".egg-info" name)
                && pkgs.lib.cleanSourceFilter path type;
            };
            build-system = [ python.pkgs.setuptools ];
            dependencies = runtime python.pkgs;
            nativeCheckInputs = with python.pkgs; [
              pytestCheckHook
              httpx
            ];
            preBuild = ''
              $CXX -O3 -std=c++17 -shared -fPIC flybet/native/kernel.cpp -o flybet/native/libflybet${pkgs.stdenv.hostPlatform.extensions.sharedLibrary}
            '';
            env.OPENBLAS_NUM_THREADS = "1";
            meta.mainProgram = "flybet";
          };
        in
        {
          inherit pkgs app;
          shell = pkgs.mkShell {
            packages = [
              (python.withPackages development)
              pkgs.stdenv.cc
              pkgs.uv
              pkgs.ruff
              pkgs.nodejs
            ];
            OPENBLAS_NUM_THREADS = "1";
            shellHook = ''
              export UV_CACHE_DIR="$PWD/.cache/uv"
              echo "Flybet: python -m flybet prepare → python -m flybet serve"
            '';
          };
        };
    in
    {
      packages = eachSystem (system: {
        default = (forSystem system).app;
      });
      apps = eachSystem (system: {
        default = {
          type = "app";
          program = "${(forSystem system).app}/bin/flybet";
          meta.description = "Local MaleCNS experiment dashboard";
        };
      });
      devShells = eachSystem (system: {
        default = (forSystem system).shell;
      });
      checks = eachSystem (system: {
        package = (forSystem system).app;
        frontend =
          let
            env = forSystem system;
          in
          env.pkgs.runCommand "flybet-frontend-check" { nativeBuildInputs = [ env.pkgs.nodejs ]; } ''
            cd ${env.app.src}
            node --test tests/*.mjs
            touch $out
          '';
      });
      formatter = eachSystem (system: (forSystem system).pkgs.nixfmt);
    };
}
