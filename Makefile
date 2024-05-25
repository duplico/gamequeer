project_name=gamequeer

builder-build :
	docker build -f builder.Dockerfile -t $(project_name)-builder:latest .

builder-run :
	docker run \
		--rm \
		-it \
		--workdir /builder/mnt \
		-v .:/builder/mnt \
		$(project_name)-builder:latest \
		/bin/bash
